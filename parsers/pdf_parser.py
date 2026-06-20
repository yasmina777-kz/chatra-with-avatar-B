import pdfplumber

def parse_pdf(file_path):
    text = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text.append(t)

    return {
        "type": "pdf",
        "text": "\n".join(text)
    }