import requests
import os

url = "https://wiki.freecad.org/Manual"
output_file = "/Users/sergunkit/.gemini/tmp/1e3dbd9fed4774c8d63141ec6be5ae2a8cdf0a226f06e016494492dcce3fc290/manual_page.html"

try:
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    response = session.get(url)
    response.raise_for_status()  # Raise an exception for bad status codes

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(response.text)

    print(f"Successfully saved page content to {output_file}")

except Exception as e:
    print(f"An error occurred: {e}")
