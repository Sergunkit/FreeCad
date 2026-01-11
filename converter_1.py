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
        if self.driver:
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
            if 'domain' in cookie:
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
            print("Could not find Table of Contents div with id='toc'. Falling back to class='manualtoc'.")
            toc = soup.find('div', class_='manualtoc')
            if not toc:
                print("Could not find fallback Table of Contents div either. The page structure may have changed.")
                # As a last resort, try to find any link to the manual
                all_links = soup.find_all('a', href=re.compile(r'/Manual:'))
                if not all_links:
                    print("No manual links found on the page at all.")
                    return {}
                print(f"Found {len(all_links)} links as a last resort.")
                for a_tag in all_links:
                    href = a_tag.get('href')
                    full_url = f"https://wiki.freecad.org{href}"
                    base_chapter = full_url.split('#')[0]
                    if base_chapter not in links:
                        links[base_chapter] = []
                return links

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
            time.sleep(5) # Increased wait time for JS challenges or dynamic content
            
            self._sync_cookies()
            
            print(f"Debug: Fetched {self.driver.current_url} successfully.")
            return self.driver.page_source
        except Exception as e:
            print(f"Error fetching {url} with Selenium: {e}")
            return None

    def extract_main_content(self, html_content, chapter_title, chapter_id):
        """Extract content within the 'mw-parser-output' div, fix links, and process image paths."""
        soup = BeautifulSoup(html_content, 'html.parser')

        for class_name in ['mw-pt-languages', 'docnav', 'NavFrame', 'manualtoc', 'toc', 'mw-jump-link', 'vector-header-container', 'mw-page-container-inner', 'mw-footer-container']:
            for element in soup.find_all(True, {'class': class_name}):
                element.decompose()
            for element in soup.find_all(id=re.compile("p-.*")): # Removes sidebars etc.
                element.decompose()


        main_content = soup.find('div', class_='mw-parser-output')
        if not main_content:
            # Fallback to body if specific div is not found
            main_content = soup.find('body')
            if not main_content:
                print("Main content ('mw-parser-output' or 'body') not found.")
                return None

        # Add a title if one isn't there
        if not main_content.find(['h1', 'h2']):
             heading_tag = soup.new_tag('h1', id=chapter_id)
             heading_tag.string = chapter_title
             main_content.insert(0, heading_tag)

        for img in main_content.find_all('img'):
            src = img.get('src')
            if src:
                if src.startswith('//'):
                    src = 'https:' + src
                
                if src.startswith('/'):
                    img_url = f"https://wiki.freecad.org{src}"
                elif src.startswith('http'):
                    img_url = src
                else:
                    continue 

                img_filename = os.path.basename(img_url.split('?')[0])
                img_data = None

                try:
                    if img_url.endswith('.svg'):
                        png_data = self.svg_to_png(img_url)
                        if png_data:
                            img_data = png_data
                            img_filename = f"{os.path.splitext(img_filename)[0]}.png"
                    else:
                        img_data = self.optimize_image(img_url)

                    if img_data:
                        img['src'] = f"data:image/png;base64,{base64.b64encode(img_data).decode('utf-8')}"
                        img['epub_src'] = img_filename
                        img['epub_data'] = img_data
                except Exception as e:
                    print(f"Could not process image {img_url}: {e}")


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
        chapter_title = soup.title.string.split(" - ")[0] if soup.title else url.split('/')[-1]
        chapter_title = chapter_title.replace("Manual:", "").strip()

        main_content = self.extract_main_content(html_content, chapter_title, chapter_id)
        if not main_content:
            return None

        output_file = os.path.join(output_dir, f"{chapter_id}.pdf")
        self.toc_entries.append((chapter_number, chapter_title, chapter_id, subchapters))

        styled_content = f"""
        <html><head><meta charset="UTF-8"><style>
        @page {{ size: A4; margin: 1.5cm; }}
        body {{ font-family: sans-serif; font-size: 11pt; }}
        h1, h2, h3, h4, h5, h6 {{ page-break-after: avoid; }}
        h1 {{ font-size: 20pt; }}
        h2 {{ font-size: 16pt; }}
        img {{ max-width: 100%; height: auto; }}
        pre, code {{ background-color: #f5f5f5; padding: 5px; border: 1px solid #ccc; white-space: pre-wrap; word-wrap: break-word; }}
        table.wikitable {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
        table.wikitable th, table.wikitable td {{ border: 1px solid #aaa; padding: 0.5em; }}
        table.wikitable th {{ background-color: #f2f2f2; }}
        </style></head><body>{main_content}</body></html>
        """

        try:
            HTML(string=styled_content, base_url=url).write_pdf(output_file)
            print(f"Created {output_file}")
            return output_file
        except Exception as e:
            print(f"Error creating PDF for {url}: {e}")
            return None

    def generate_toc_pdf(self, output_file='pdfs/00_Table_of_Contents.pdf'):
        """Generate a Table of Contents PDF with indented subchapters."""
        print("Generating Table of Contents PDF...")
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        self.toc_entries.sort(key=lambda x: x[0])
        
        toc_html = "<html><head><title>Table of Contents</title></head><body><h1>Table of Contents</h1><ul>"
        for chapter_number, title, chapter_id, subchapters in self.toc_entries:
            toc_html += f'<li><a href="{chapter_id}.pdf">{chapter_number}. {title}</a></li>'
            if subchapters:
                toc_html += "<ul style='margin-left: 25px;'>"
                for i, sub in enumerate(subchapters, start=1):
                    toc_html += f'<li>{chapter_number}.{i} {sub.replace("_", " ")}</li>'
                toc_html += "</ul>"
        toc_html += "</ul></body></html>"

        try:
            HTML(string=toc_html).write_pdf(output_file)
            print(f"Created {output_file}")
        except Exception as e:
            print(f"Error creating Table of Contents PDF: {e}")

    def merge_pdfs(self, pdf_files, output_file):
        print(f"Merging PDFs into {output_file}...")
        merger = PdfMerger()
        for pdf in pdf_files:
            if os.path.exists(pdf):
                try:
                    merger.append(pdf)
                except Exception as e:
                    print(f"Could not append {pdf}: {e}")
            else:
                print(f"File not found, skipping: {pdf}")
        try:
            merger.write(output_file)
            merger.close()
            print(f"Successfully created {output_file}")
        except Exception as e:
            print(f"Error merging PDFs: {e}")

    def create_epub(self, output_file='FreeCAD_User_Manual.epub'):
        print(f"Creating EPUB: {output_file}")
        book = epub.EpubBook()
        book.set_identifier(str(uuid.uuid4()))
        book.set_title('FreeCAD User Manual')
        book.set_language('en')
        book.add_author('FreeCAD Community')
        
        # Add a simple cover
        try:
            from PIL import Image, ImageDraw, ImageFont
            cover_img = Image.new('RGB', (800, 1200), color = '#2c3e50')
            draw = ImageDraw.Draw(cover_img)
            try:
                # Use a common font, fallback to default
                font = ImageFont.truetype("Arial.ttf", 60)
                small_font = ImageFont.truetype("Arial.ttf", 30)
            except IOError:
                font = ImageFont.load_default()
                small_font = font
            draw.text((400, 500), "FreeCAD User Manual", font=font, fill='#ecf0f1', anchor="mm")
            draw.text((400, 600), datetime.now().strftime('%Y-%m-%d'), font=small_font, fill='#bdc3c7', anchor="mm")
            
            img_byte_arr = BytesIO()
            cover_img.save(img_byte_arr, format='PNG')
            book.set_cover("cover.png", img_byte_arr.getvalue())
        except Exception as e:
            print(f"Could not create EPUB cover image: {e}")

        # CSS styles
        style = '''
        @namespace epub "http://www.idpf.org/2007/ops";
        body { font-family: sans-serif; }
        h1 { text-align: center; }
        img { max-width: 95%; display: block; margin-left: auto; margin-right: auto; }
        pre { background-color: #eee; padding: 1em; white-space: pre-wrap; border-radius: 5px; }
        '''
        default_css = epub.EpubItem(uid="style_default", file_name="style/default.css", media_type="text/css", content=style)
        book.add_item(default_css)

        epub_chapters = []
        # Create a title page
        title_page = epub.EpubHtml(title='Title Page', file_name='title.xhtml')
        title_page.content='<h1 style="font-size: 2em;">FreeCAD User Manual</h1>'
        book.add_item(title_page)


        for chapter_data in sorted(self.chapters_html, key=lambda x: x['number']):
            file_name = f'chapter_{chapter_data["number"]}.xhtml'
            
            # Create chapter from the cleaned content
            soup = chapter_data['content']
            for img in soup.find_all('img', {'epub_data': True}):
                try:
                    img_hash = hashlib.md5(img['epub_data']).hexdigest()
                    img_filename = f'images/{img_hash}_{img["epub_src"]}'
                    if not any(item.file_name == img_filename for item in book.get_items()):
                        image_item = epub.EpubImage(uid=f'img_{img_hash}', file_name=img_filename, media_type='image/png', content=img['epub_data'])
                        book.add_item(image_item)
                    img['src'] = img_filename
                    del img['epub_data'], img['epub_src']
                except Exception as e:
                    print(f"Could not add image to EPUB: {e}")

            chapter = epub.EpubHtml(title=chapter_data['title'], file_name=file_name, lang='en')
            chapter.content = f"<h2>{chapter_data['title']}</h2>{str(soup)}"
            chapter.add_item(default_css)
            book.add_item(chapter)
            epub_chapters.append(chapter)

        book.toc = (epub.Link('title.xhtml', 'Title', 'title'), (epub.Section('Chapters'), tuple(epub_chapters)))
        book.spine = ['nav', title_page] + epub_chapters

        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        epub.write_epub(output_file, book, {})
        print(f"Successfully created {output_file}")


    def batch_convert(self, links, output_dir='pdfs', merged_pdf='FreeCAD_User_Manual.pdf', create_epub_flag=True):
        os.makedirs(output_dir, exist_ok=True)
        pdf_files = []
        
        sorted_links = sorted(links.items())

        for chapter_number, (chapter_url, subchapters) in enumerate(sorted_links, start=1):
            chapter_id = re.sub(r'[\W_]+', '_', chapter_url.split('/')[-1])
            pdf_file = self.convert_to_pdf(chapter_url, chapter_number, chapter_id, subchapters, output_dir)
            if pdf_file:
                pdf_files.append(pdf_file)
        
        toc_pdf_path = os.path.join(output_dir, '00_Table_of_Contents.pdf')
        self.generate_toc_pdf(toc_pdf_path)
        
        all_pdfs = [toc_pdf_path] + pdf_files
        self.merge_pdfs(all_pdfs, merged_pdf)

        if create_epub_flag:
            self.create_epub('FreeCAD_User_Manual.epub')

def main():
    converter = FreeCADManualConverter()
    if not converter.driver:
        print("Failed to initialize Selenium WebDriver. Exiting.")
        return
        
    try:
        manual_links = converter.extract_manual_links()
        if manual_links:
            converter.batch_convert(manual_links, 
                                    output_dir='pdfs',
                                    merged_pdf='FreeCAD_User_Manual.pdf',
                                    create_epub_flag=True)
        else:
            print("No manual links were found. Cannot proceed.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if converter:
            converter.close()

if __name__ == "__main__":
    main()
