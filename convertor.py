import requests
from weasyprint import HTML
import os
from bs4 import BeautifulSoup
import re
from PyPDF2 import PdfMerger
from PIL import Image
from io import BytesIO
import base64
import cairosvg
import ebooklib
from ebooklib import epub
import uuid
from datetime import datetime
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options


class FreeCADManualConverter:
    def __init__(self):
        self.session = requests.Session()
        self.driver = self._init_driver()
        # Update session headers after driver is initialized
        self.session.headers.update({
            'User-Agent': self.driver.execute_script("return navigator.userAgent;")
        })
        self.toc_entries = []
        self.chapters_html = []
        self.image_cache = {}

    def _init_driver(self):
        """Initializes and returns a Selenium WebDriver."""
        print("Initializing browser...")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        try:
            driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
            print("Browser initialized.")
            return driver
        except Exception as e:
            print(f"Error initializing WebDriver: {e}")
            return None

    def close(self):
        """Closes the selenium driver."""
        if self.driver:
            print("Closing browser.")
            self.driver.quit()

    def _sync_cookies(self):
        """Syncs cookies from Selenium driver to requests session."""
        if not self.driver:
            return
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

    def optimize_image(self, img_url, max_width=800):
        """Download and optimize a raster image."""
        try:
            # Use the session which has cookies from the driver
            response = self.session.get(img_url, stream=True, timeout=20)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            if img.width > max_width:
                img = img.resize((max_width, int(img.height * max_width / img.width)), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="PNG", optimize=True)
            buffer.seek(0)
            return buffer.read()
        except Exception as e:
            print(f"Error optimizing image {img_url}: {e}")
            return None

    def svg_to_png(self, svg_url):
        """Convert SVG to PNG."""
        try:
            # Use the session which has cookies from the driver
            response = self.session.get(svg_url, timeout=20)
            response.raise_for_status()
            return cairosvg.svg2png(bytestring=response.content, output_width=16, output_height=16)
        except Exception as e:
            print(f"Error converting SVG {svg_url} to PNG: {e}")
            return None

    def extract_manual_links(self, base_url="https://wiki.freecad.org/Manual:Introduction"):
        """Extract all manual links from the main Manual page."""
        print(f"Fetching manual links from {base_url}...")
        html_content = self.fetch_page(base_url)
        if not html_content:
            return {}

        soup = BeautifulSoup(html_content, 'html.parser')
        links = {}
        
        # The TOC is now the reliable source for links
        toc = soup.find('div', id='toc')
        if not toc:
            print("Could not find Table of Contents div.")
            return {}

        for a_tag in toc.find_all('a', href=True):
            href = a_tag.get('href')
            if href.startswith('/Manual:'):
                full_url = f"https://wiki.freecad.org{href}"
                base_chapter = full_url.split('#')[0]
                subchapter = full_url.split('#')[1] if '#' in full_url else None

                if base_chapter not in links:
                    links[base_chapter] = []

                if subchapter:
                    links[base_chapter].append(subchapter)
        
        # Add the base introduction page itself if it's not there
        if base_url not in links:
             links[base_url] = []

        print(f"Found {len(links)} unique manual pages.")
        return links

    def fetch_page(self, url):
        """Fetch the HTML content of a given URL using Selenium."""
        if not self.driver:
            print("Driver not initialized.")
            return None
        
        if url.startswith('/'):
            url = f"https://wiki.freecad.org{url}"

        try:
            print(f"Fetching page via browser: {url}")
            self.driver.get(url)
            time.sleep(3) # Wait for JS challenges or dynamic content
            
            # Sync cookies to requests session for image downloads
            self._sync_cookies()
            
            print(f"Debug: Fetched {self.driver.current_url} successfully.")
            # Сохраняем HTML для отладки
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            return self.driver.page_source
        except Exception as e:
            print(f"Error fetching {url} with Selenium: {e}")
            return None

    def extract_main_content(self, html_content, base_url, chapter_title, chapter_id, subchapters):
        """Extract content within the 'mw-parser-output' div, fix links, and process image
       paths."""
        soup = BeautifulSoup(html_content, 'html.parser')

        for class_name in ['mw-pt-languages noprint', 'docnav', 'NavFrame', 'manualtoc']:
            for element in soup.find_all(class_=class_name):
                element.decompose()

        main_content = soup.find('div', class_='mw-parser-output')
        if not main_content:
            print("Main content ('mw-parser-output') not found.")
            return None

        if not main_content.find('h1', id=chapter_id):
            heading_tag = soup.new_tag('h1', id=chapter_id)
            heading_tag.string = chapter_title
            main_content.insert(0, heading_tag)

        for img in main_content.find_all('img'):
            src = img.get('src')
            if src:
                # Resolve relative URLs
                if src.startswith('/'):
                    img_url = f"https://wiki.freecad.org{src}"
                elif src.startswith('http'):
                    img_url = src
                else:
                    continue # Skip data URIs or other formats for now

                img_filename = os.path.basename(img_url.split('?')[0])
                img_data = None

                if img_url.endswith('.svg'):
                    png_data = self.svg_to_png(img_url)
                    if png_data:
                        img_data = png_data
                        img_filename = f"{img_filename[:-4]}.png"
                else:
                    img_data = self.optimize_image(img_url)

                if img_data:
                    img['src'] = f"data:image/png;base64,{base64.b64encode(img_data).decode('utf-8')}"
                    img['epub_src'] = img_filename
                    img['epub_data'] = img_data

        for link in main_content.find_all('a'):
            href = link.get('href')
            if href and href.startswith('/'):
                link['href'] = f"https://wiki.freecad.org{href}"

        self.chapters_html.append({
            'title': chapter_title,
            'id': chapter_id,
            'content': main_content,
            'number': len(self.chapters_html) + 1
        })

        return str(main_content)

    def convert_to_pdf(self, url, chapter_number, chapter_id, subchapters, output_dir='pdfs'):
        print(f"Processing {url}...")
        os.makedirs(output_dir, exist_ok=True)

        html_content = self.fetch_page(url)
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        chapter_title = soup.title.string.split(" - ")[0] if soup.title else "Chapter"
        chapter_title = chapter_title.replace("Manual:", "").strip()

        base_url = "https://wiki.freecad.org"
        main_content = self.extract_main_content(html_content, base_url, chapter_title, chapter_id, subchapters)
        if not main_content:
            return None

        output_file = os.path.join(output_dir, f"{chapter_id}.pdf")
        self.toc_entries.append((chapter_number, chapter_title, chapter_id, subchapters))

        styled_content = f"""
        <html><head><style>
        body {{ margin: 20px; font-family: sans-serif; }}
        h1 {{ text-align: center; font-size: 24px; margin-bottom: 10px; }}
        h2 {{ font-size: 18px; margin-top: 10px; }}
        img {{ max-width: 100%; height: auto; }}
        code, pre {{ font-family: monospace; font-size: 14px; background-color: #f4f4f4; padding: 10px; display: block; white-space: pre-wrap; word-wrap: break-word; overflow-x: auto; border: 1px solid #ddd; border-radius: 5px; }}
        .mw-highlight {{ padding: 10px; margin: 10px 0; border: 1px solid #ddd; background-color: #f9f9f9; border-radius: 5px; }}
        .wikitable {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; text-align: left; page-break-inside: avoid; }}
        .wikitable th, .wikitable td {{ border: 1px solid #ddd; padding: 10px; page-break-inside: avoid; }}
        .wikitable tr {{ page-break-inside: avoid; }}
        .wikitable tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .wikitable tr:hover {{ background-color: #f1f1f1; }}
        .wikitable th {{ background-color: #f2f2f2; text-align: center; font-weight: bold;}}
        </style></head><body>{main_content}</body></html>
        """

        try:
            HTML(string=styled_content).write_pdf(output_file)
            print(f"Created {output_file}")
            return output_file
        except Exception as e:
            print(f"Error creating PDF for {url}: {e}")
            return None

    def generate_toc(self, output_file='pdfs/Table_of_Contents.pdf'):
        """Generate a Table of Contents PDF with indented subchapters."""
        print("Generating Table of Contents...")
        toc_html = "<html><head><title>Table of Contents</title></head><body><h1>Table of Contents</h1><ul>"
        
        # Sort entries by chapter number before generating
        self.toc_entries.sort(key=lambda x: x[0])

        for chapter_number, title, chapter_id, subchapters in self.toc_entries:
            toc_html += f'<li class="chapter">{chapter_number}. <a href="#{chapter_id}">{title}</a></li>'
            for i, sub in enumerate(subchapters, start=1):
                toc_html += f'<li class="subchapter" style="margin-left: 20px;">{chapter_number}.{i} <a href="#{chapter_id}_{sub}">{sub.replace("_", " ").capitalize()}</a></li>'

        toc_html += "</ul></body></html>"

        try:
            HTML(string=toc_html).write_pdf(output_file)
            print(f"Created {output_file}")
        except Exception as e:
            print(f"Error creating Table of Contents PDF: {e}")

    def merge_pdfs(self, pdf_files, output_file):
        print(f"Merging PDFs into {output_file}...")
        merger = PdfMerger()
        for pdf in sorted(pdf_files): # Sort files to ensure TOC is first
            if os.path.exists(pdf):
                merger.append(pdf)
        merger.write(output_file)
        merger.close()
        print(f"Successfully created {output_file}")

    def create_epub(self, output_file='FreeCAD_User_Manual.epub'):
        print(f"Creating EPUB: {output_file}")
        book = epub.EpubBook()
        book.set_identifier(str(uuid.uuid4()))
        book.set_title('FreeCAD User Manual')
        book.set_language('en')
        book.add_author('FreeCAD Community')
        try:
            book.set_cover("cover.jpg", self.generate_cover())
        except Exception as e:
            print(f"Could not generate cover: {e}")

        style = '''
            body { margin: 20px; font-family: sans-serif; } h1 { text-align: center; font-size: 2em; } h2 { font-size: 1.5em; }
            img { max-width: 100%; height: auto; } code, pre { font-family: monospace; background-color: #f4f4f4; padding: 0.5em; display: block; white-space: pre-wrap; border: 1px solid #ddd; }
            table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid #ddd; padding: 0.5em; }
        '''
        nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
        book.add_item(nav_css)

        chapters = []
        for chapter_data in sorted(self.chapters_html, key=lambda x: x['number']):
            chapter = epub.EpubHtml(title=chapter_data['title'], file_name=f'chapter_{chapter_data["number"]}.xhtml', lang='en')
            content = chapter_data['content']
            for img in content.find_all('img'):
                if 'epub_data' in img.attrs and 'epub_src' in img.attrs:
                    import hashlib
                    img_hash = hashlib.md5(img['epub_data']).hexdigest()
                    if img_hash not in self.image_cache:
                        image_filename = f'{img_hash}_{img["epub_src"]}'
                        self.image_cache[img_hash] = image_filename
                        image_item = epub.EpubItem(uid=f'image_{img_hash}', file_name=f'images/{image_filename}', media_type='image/png', content=img['epub_data'])
                        book.add_item(image_item)
                    img['src'] = f'images/{self.image_cache[img_hash]}'
                    del img['epub_data']
                    del img['epub_src']
            chapter.content = str(content)
            chapter.add_item(nav_css)
            book.add_item(chapter)
            chapters.append(chapter)

        book.toc = [(epub.Section('Table of Contents'), chapters)]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ['nav'] + chapters
        epub.write_epub(output_file, book, {{}})
        print(f"Successfully created {output_file}")

    def generate_cover(self):
        """Generate a simple cover image for the EPUB."""
        from PIL import Image, ImageDraw, ImageFont
        cover = Image.new('RGB', (1600, 2400), 'white')
        draw = ImageDraw.Draw(cover)
        try:
            font_large = ImageFont.truetype("Arial.ttf", 120)
            font_small = ImageFont.truetype("Arial.ttf", 80)
        except IOError:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        title = "FreeCAD\nUser Manual"
        draw.text((800, 1000), title, font=font_large, fill='black', anchor="mm", align="center")
        date_str = datetime.now().strftime("%Y-%m-%d")
        draw.text((800, 1300), date_str, font=font_small, fill='gray', anchor="mm")
        
        img_byte_arr = BytesIO()
        cover.save(img_byte_arr, format='JPEG')
        return img_byte_arr.getvalue()

    def batch_convert(self, links, output_dir='pdfs', merged_pdf='FreeCAD_User_Manual.pdf', create_epub=True):
        """Convert manual to both PDF and EPUB formats."""
        os.makedirs(output_dir, exist_ok=True)
        pdf_files = []
        
        sorted_links = sorted(links.items())

        for chapter_number, (chapter_url, subchapters) in enumerate(sorted_links, start=1):
            chapter_id = re.sub(r'[<>:"/\\?*]', '_', chapter_url.split('/')[-1])
            pdf_file = self.convert_to_pdf(chapter_url, chapter_number, chapter_id, subchapters, output_dir)
            if pdf_file:
                pdf_files.append(pdf_file)

        toc_file = os.path.join(output_dir, "00_Table_of_Contents.pdf")
        self.generate_toc(toc_file)
        
        all_pdfs = [toc_file] + pdf_files
        if all_pdfs:
            self.merge_pdfs(all_pdfs, merged_pdf)

        if create_epub:
            self.create_epub('FreeCAD_User_Manual.epub')

def main():
    converter = FreeCADManualConverter()
    if not converter.driver:
        return
        
    try:
        manual_links = converter.extract_manual_links()
        if manual_links:
            converter.batch_convert(manual_links, output_dir='pdfs',
                              merged_pdf='FreeCAD_User_Manual.pdf',
                              create_epub=True)
        else:
            print("No manual links were found. Cannot proceed.")
    finally:
        converter.close()

if __name__ == "__main__":
    main()