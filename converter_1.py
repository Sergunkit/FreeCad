import requests
     2 from weasyprint import HTML
     3 import os
     4 from bs4 import BeautifulSoup
     5 import re
     6 from PyPDF2 import PdfMerger
     7 from PIL import Image
     8 from io import BytesIO
     9 import base64
    10 import cairosvg
    11 import ebooklib
    12 from ebooklib import epub
    13 import uuid
    14 from datetime import datetime
    15 import time
    16 
    17 from selenium import webdriver
    18 from selenium.webdriver.chrome.service import Service as ChromeService
    19 from webdriver_manager.chrome import ChromeDriverManager
    20 from selenium.webdriver.chrome.options import Options
    21 
    22 
    23 class FreeCADManualConverter:
    24     def __init__(self):
    25         self.session = requests.Session()
    26         self.driver = self._init_driver()
    27         # Update session headers after driver is initialized
    28         self.session.headers.update({
    29             'User-Agent': self.driver.execute_script("return navigator.userAgent;")
    30         })
    31         self.toc_entries = []
    32         self.chapters_html = []
    33         self.image_cache = {}
    34 
    35     def _init_driver(self):
    36         """Initializes and returns a Selenium WebDriver."""
    37         print("Initializing browser...")
    38         chrome_options = Options()
    39         chrome_options.add_argument("--headless")
    40         chrome_options.add_argument("--disable-gpu")
    41         chrome_options.add_argument("--no-sandbox")
    42         try:
    43             driver = 
       webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), 
       options=chrome_options)
    44             print("Browser initialized.")
    45             return driver
    46         except Exception as e:
    47             print(f"Error initializing WebDriver: {e}")
    48             return None
    49 
    50     def close(self):
    51         """Closes the selenium driver."""
    52         if self.driver:
    53             print("Closing browser.")
    54             self.driver.quit()
    55 
    56     def _sync_cookies(self):
    57         """Syncs cookies from Selenium driver to requests session."""
    58         if not self.driver:
    59             return
    60         for cookie in self.driver.get_cookies():
    61             self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domai
       ])
    62 
    63     def optimize_image(self, img_url, max_width=800):
    64         """Download and optimize a raster image."""
    65         try:
    66             # Use the session which has cookies from the driver
    67             response = self.session.get(img_url, stream=True, timeout=20)
    68             response.raise_for_status()
    69             img = Image.open(BytesIO(response.content))
    70             if img.width > max_width:
    71                 img = img.resize((max_width, int(img.height * max_width / img.width)), 
       Image.Resampling.LANCZOS)
    72             buffer = BytesIO()
    73             img.save(buffer, format="PNG", optimize=True)
    74             buffer.seek(0)
    75             return buffer.read()
    76         except Exception as e:
    77             print(f"Error optimizing image {img_url}: {e}")
    78             return None
    79 
    80     def svg_to_png(self, svg_url):
    81         """Convert SVG to PNG."""
    82         try:
    83             # Use the session which has cookies from the driver
    84             response = self.session.get(svg_url, timeout=20)
    85             response.raise_for_status()
    86             return cairosvg.svg2png(bytestring=response.content, output_width=16, 
       output_height=16)
    87         except Exception as e:
    88             print(f"Error converting SVG {svg_url} to PNG: {e}")
    89             return None
    90 
    91     def extract_manual_links(self, base_url="https://wiki.freecad.org/Manual:Introduction"
    92         """Extract all manual links from the main Manual page."""
    93         print(f"Fetching manual links from {base_url}...")
    94         html_content = self.fetch_page(base_url)
    95         if not html_content:
    96             return {}
    97 
    98         soup = BeautifulSoup(html_content, 'html.parser')
    99         links = {}
   100         
   101         # The TOC is now the reliable source for links
   102         toc = soup.find('div', id='toc')
   103         if not toc:
   104             print("Could not find Table of Contents div.")
   105             return {}
   106 
   107         for a_tag in toc.find_all('a', href=True):
   108             href = a_tag.get('href')
   109             if href.startswith('/Manual:'):
   110                 full_url = f"https://wiki.freecad.org{href}"
   111                 base_chapter = full_url.split('#')[0]
   112                 subchapter = full_url.split('#')[1] if '#' in full_url else None
   113 
   114                 if base_chapter not in links:
   115                     links[base_chapter] = []
   116 
   117                 if subchapter:
   118                     links[base_chapter].append(subchapter)
   119         
   120         # Add the base introduction page itself if it's not there
   121         if base_url not in links:
   122              links[base_url] = []
   123 
   124         print(f"Found {len(links)} unique manual pages.")
   125         return links
   126 
   127     def fetch_page(self, url):
   128         """Fetch the HTML content of a given URL using Selenium."""
   129         if not self.driver:
   130             print("Driver not initialized.")
   131             return None
   132         
   133         if url.startswith('/'):
   134             url = f"https://wiki.freecad.org{url}"
   135 
   136         try:
   137             print(f"Fetching page via browser: {url}")
   138             self.driver.get(url)
   139             time.sleep(3) # Wait for JS challenges or dynamic content
   140             
   141             # Sync cookies to requests session for image downloads
   142             self._sync_cookies()
   143             
   144             print(f"Debug: Fetched {self.driver.current_url} successfully.")
   145             return self.driver.page_source
   146         except Exception as e:
   147             print(f"Error fetching {url} with Selenium: {e}")
   148             return None
   149 
   150     def extract_main_content(self, html_content, base_url, chapter_title, chapter_id, 
       subchapters):
   151         """Extract content within the 'mw-parser-output' div, fix links, and process image
       paths."""
   152         soup = BeautifulSoup(html_content, 'html.parser')
   153 
   154         for class_name in ['mw-pt-languages noprint', 'docnav', 'NavFrame', 'manualtoc']:
   155             for element in soup.find_all(class_=class_name):
   156                 element.decompose()
   157 
   158         main_content = soup.find('div', class_='mw-parser-output')
   159         if not main_content:
   160             print("Main content ('mw-parser-output') not found.")
   161             return None
   162 
   163         if not main_content.find('h1', id=chapter_id):
   164             heading_tag = soup.new_tag('h1', id=chapter_id)
   165             heading_tag.string = chapter_title
   166             main_content.insert(0, heading_tag)
   167 
   168         for img in main_content.find_all('img'):
   169             src = img.get('src')
   170             if src:
   171                 # Resolve relative URLs
   172                 if src.startswith('/'):
   173                     img_url = f"https://wiki.freecad.org{src}"
   174                 elif src.startswith('http'):
   175                     img_url = src
   176                 else:
   177                     continue # Skip data URIs or other formats for now
   178 
   179                 img_filename = os.path.basename(img_url.split('?')[0])
   180                 img_data = None
   181 
   182                 if img_url.endswith('.svg'):
   183                     png_data = self.svg_to_png(img_url)
   184                     if png_data:
   185                         img_data = png_data
   186                         img_filename = f"{img_filename[:-4]}.png"
   187                 else:
   188                     img_data = self.optimize_image(img_url)
   189 
   190                 if img_data:
   191                     img['src'] = f"data:image/png;base64,{base64.b64encode(img_data).decod
       'utf-8')}"
   192                     img['epub_src'] = img_filename
   193                     img['epub_data'] = img_data
   194 
   195         for link in main_content.find_all('a'):
   196             href = link.get('href')
   197             if href and href.startswith('/'):
   198                 link['href'] = f"https://wiki.freecad.org{href}"
   199 
   200         self.chapters_html.append({
   201             'title': chapter_title,
   202             'id': chapter_id,
   203             'content': main_content,
   204             'number': len(self.chapters_html) + 1
   205         })
   206 
   207         return str(main_content)
   208 
   209     def convert_to_pdf(self, url, chapter_number, chapter_id, subchapters, output_dir='pdf
       ):
   210         print(f"Processing {url}...")
   211         os.makedirs(output_dir, exist_ok=True)
   212 
   213         html_content = self.fetch_page(url)
   214         if not html_content:
   215             return None
   216 
   217         soup = BeautifulSoup(html_content, 'html.parser')
   218         chapter_title = soup.title.string.split(" - ")[0] if soup.title else "Chapter"
   219         chapter_title = chapter_title.replace("Manual:", "").strip()
   220 
   221         base_url = "https://wiki.freecad.org"
   222         main_content = self.extract_main_content(html_content, base_url, chapter_title, 
       chapter_id, subchapters)
   223         if not main_content:
   224             return None
   225 
   226         output_file = os.path.join(output_dir, f"{chapter_id}.pdf")
   227         self.toc_entries.append((chapter_number, chapter_title, chapter_id, subchapters))
   228 
   229         styled_content = f"""
   230         <html><head><style>
   231         body {{ margin: 20px; font-family: sans-serif; }}
   232         h1 {{ text-align: center; font-size: 24px; margin-bottom: 10px; }}
   233         h2 {{ font-size: 18px; margin-top: 10px; }}
   234         img {{ max-width: 100%; height: auto; }}
   235         code, pre {{ font-family: monospace; font-size: 14px; background-color: #f4f4f4; 
       padding: 10px; display: block; white-space: pre-wrap; word-wrap: break-word; overflow-x: 
       auto; border: 1px solid #ddd; border-radius: 5px; }}
   236         .mw-highlight {{ padding: 10px; margin: 10px 0; border: 1px solid #ddd; 
       background-color: #f9f9f9; border-radius: 5px; }}
   237         .wikitable {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 
       14px; text-align: left; page-break-inside: avoid; }}
   238         .wikitable th, .wikitable td {{ border: 1px solid #ddd; padding: 10px; 
       page-break-inside: avoid; }}
   239         .wikitable tr {{ page-break-inside: avoid; }}
   240         .wikitable tr:nth-child(even) {{ background-color: #f9f9f9; }}
   241         .wikitable tr:hover {{ background-color: #f1f1f1; }}
   242         .wikitable th {{ background-color: #f2f2f2; text-align: center; font-weight: bold;
       }}
   243         </style></head><body>{main_content}</body></html>
   244         """
   245 
   246         try:
   247             HTML(string=styled_content).write_pdf(output_file)
   248             print(f"Created {output_file}")
   249             return output_file
   250         except Exception as e:
   251             print(f"Error creating PDF for {url}: {e}")
   252             return None
   253 
   254     def generate_toc(self, output_file='pdfs/Table_of_Contents.pdf'):
   255         """Generate a Table of Contents PDF with indented subchapters."""
   256         print("Generating Table of Contents...")
   257         toc_html = "<html><head><title>Table of Contents</title></head><body><h1>Table of 
       Contents</h1><ul>"
   258         
   259         # Sort entries by chapter number before generating
   260         self.toc_entries.sort(key=lambda x: x[0])
   261 
   262         for chapter_number, title, chapter_id, subchapters in self.toc_entries:
   263             toc_html += f'<li class="chapter">{chapter_number}. <a href="#{chapter_id}">
       {title}</a></li>'
   264             for i, sub in enumerate(subchapters, start=1):
   265                 toc_html += f'<li class="subchapter" style="margin-left: 20px;">
       {chapter_number}.{i} <a href="#{chapter_id}_{sub}">{sub.replace("_", " ").capitalize()}
       </a></li>'
   266 
   267         toc_html += "</ul></body></html>"
   268 
   269         try:
   270             HTML(string=toc_html).write_pdf(output_file)
   271             print(f"Created {output_file}")
   272         except Exception as e:
   273             print(f"Error creating Table of Contents PDF: {e}")
   274 
   275     def merge_pdfs(self, pdf_files, output_file):
   276         print(f"Merging PDFs into {output_file}...")
   277         merger = PdfMerger()
   278         for pdf in sorted(pdf_files): # Sort files to ensure TOC is first
   279             if os.path.exists(pdf):
   280                 merger.append(pdf)
   281         merger.write(output_file)
   282         merger.close()
   283         print(f"Successfully created {output_file}")
   284 
   285     def create_epub(self, output_file='FreeCAD_User_Manual.epub'):
   286         print(f"Creating EPUB: {output_file}")
   287         book = epub.EpubBook()
   288         book.set_identifier(str(uuid.uuid4()))
   289         book.set_title('FreeCAD User Manual')
   290         book.set_language('en')
   291         book.add_author('FreeCAD Community')
   292         try:
   293             book.set_cover("cover.jpg", self.generate_cover())
   294         except Exception as e:
   295             print(f"Could not generate cover: {e}")
   296 
   297         style = '''
   298             body { margin: 20px; font-family: sans-serif; } h1 { text-align: center; 
       font-size: 2em; } h2 { font-size: 1.5em; }
   299             img { max-width: 100%; height: auto; } code, pre { font-family: monospace; 
       background-color: #f4f4f4; padding: 0.5em; display: block; white-space: pre-wrap; border: 
       1px solid #ddd; }
   300             table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid 
       #ddd; padding: 0.5em; }
   301         '''
   302         nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type=
       "text/css", content=style)
   303         book.add_item(nav_css)
   304 
   305         chapters = []
   306         for chapter_data in sorted(self.chapters_html, key=lambda x: x['number']):
   307             chapter = epub.EpubHtml(title=chapter_data['title'], file_name=f'chapter_
       {chapter_data["number"]}.xhtml', lang='en')
   308             content = chapter_data['content']
   309             for img in content.find_all('img'):
   310                 if 'epub_data' in img.attrs and 'epub_src' in img.attrs:
   311                     import hashlib
   312                     img_hash = hashlib.md5(img['epub_data']).hexdigest()
   313                     if img_hash not in self.image_cache:
   314                         image_filename = f'{img_hash}_{img["epub_src"]}'
   315                         self.image_cache[img_hash] = image_filename
   316                         image_item = epub.EpubItem(uid=f'image_{img_hash}', file_name=
       f'images/{image_filename}', media_type='image/png', content=img['epub_data'])
   317                         book.add_item(image_item)
   318                     img['src'] = f'images/{self.image_cache[img_hash]}'
   319                     del img['epub_data']
   320                     del img['epub_src']
   321             chapter.content = str(content)
   322             chapter.add_item(nav_css)
   323             book.add_item(chapter)
   324             chapters.append(chapter)
   325 
   326         book.toc = [(epub.Section('Table of Contents'), chapters)]
   327         book.add_item(epub.EpubNcx())
   328         book.add_item(epub.EpubNav())
   329         book.spine = ['nav'] + chapters
   330         epub.write_epub(output_file, book, {})
   331         print(f"Successfully created {output_file}")
   332 
   333     def generate_cover(self):
   334         """Generate a simple cover image for the EPUB."""
   335         from PIL import Image, ImageDraw, ImageFont
   336         cover = Image.new('RGB', (1600, 2400), 'white')
   337         draw = ImageDraw.Draw(cover)
   338         try:
   339             font_large = ImageFont.truetype("Arial.ttf", 120)
   340             font_small = ImageFont.truetype("Arial.ttf", 80)
   341         except IOError:
   342             font_large = ImageFont.load_default()
   343             font_small = ImageFont.load_default()
   344         
   345         title = "FreeCAD\nUser Manual"
   346         draw.text((800, 1000), title, font=font_large, fill='black', anchor="mm", align=
       "center")
   347         date_str = datetime.now().strftime("%Y-%m-%d")
   348         draw.text((800, 1300), date_str, font=font_small, fill='gray', anchor="mm")
   349         
   350         img_byte_arr = BytesIO()
   351         cover.save(img_byte_arr, format='JPEG')
   352         return img_byte_arr.getvalue()
   353 
   354     def batch_convert(self, links, output_dir='pdfs', merged_pdf='FreeCAD_User_Manual.pdf'
       create_epub=True):
   355         """Convert manual to both PDF and EPUB formats."""
   356         os.makedirs(output_dir, exist_ok=True)
   357         pdf_files = []
   358         
   359         sorted_links = sorted(links.items())
   360 
   361         for chapter_number, (chapter_url, subchapters) in enumerate(sorted_links, start=1)
   362             chapter_id = re.sub(r'[<>:"/\\?*]', '_', chapter_url.split('/')[-1])
   363             pdf_file = self.convert_to_pdf(chapter_url, chapter_number, chapter_id, 
       subchapters, output_dir)
   364             if pdf_file:
   365                 pdf_files.append(pdf_file)
   366 
   367         toc_file = os.path.join(output_dir, "00_Table_of_Contents.pdf")
   368         self.generate_toc(toc_file)
   369         
   370         all_pdfs = [toc_file] + pdf_files
   371         if all_pdfs:
   372             self.merge_pdfs(all_pdfs, merged_pdf)
   373 
   374         if create_epub:
   375             self.create_epub('FreeCAD_User_Manual.epub')
   376 
   377 def main():
   378     converter = FreeCADManualConverter()
   379     if not converter.driver:
   380         return
   381         
   382     try:
   383         manual_links = converter.extract_manual_links()
   384         if manual_links:
   385             converter.batch_convert(manual_links, output_dir='pdfs',
   386                               merged_pdf='FreeCAD_User_Manual.pdf',
   387                               create_epub=True)
   388         else:
   389             print("No manual links were found. Cannot proceed.")
   390     finally:
   391         converter.close()
   392 
   393 if __name__ == "__main__":
   394     main()
