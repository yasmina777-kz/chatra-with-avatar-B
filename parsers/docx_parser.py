from docx import Document

def parse_docx(file_path):
    doc = Document(file_path)

    text = [p.text for p in doc.paragraphs]

    return {
        "type": "docx",
        "text": "\n".join(text)
    }