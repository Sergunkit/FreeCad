# FreeCAD Manual Downloader

This script downloads the FreeCAD Manual from the official wiki and converts it into PDF and EPUB formats. It supports downloading the manual in multiple languages.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone git remote add origin git@github.com:Sergunkit/FreeCad.git
    cd FREECAD
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the required dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Usage

Run the script from the command line. You can specify a language for the manual using the `--lang` flag. If no language is specified, it will download the English version by default.

### Download the English Manual

```bash
python3 converter_1.py
```

### Download the Russian Manual

```bash
python3 converter_1.py --lang ru
```

### Download the German Manual

```bash
python3 converter_1.py --lang de
```

The output files (e.g., `FreeCAD_User_Manual_ru.pdf` and `FreeCAD_User_Manual_ru.epub`) will be saved in the project's root directory. Intermediate PDF files for each chapter will be stored in the `pdfs/` directory.
