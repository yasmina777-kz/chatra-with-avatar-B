from parsers.txt_parser import parse_txt
from parsers.docx_parser import parse_docx
from parsers.pdf_parser import parse_pdf
from parsers.sm_parser import parse_sm
from parsers.excel_parser import parse_excel
from parsers.image_parser import parse_image

def read_file(file_path):
    file_path_lower = file_path.lower()

    if file_path_lower.endswith(".txt"):
        return parse_txt(file_path)

    elif file_path_lower.endswith(".docx"):
        return parse_docx(file_path)

    elif file_path_lower.endswith(".pdf"):
        return parse_pdf(file_path)

    elif file_path_lower.endswith(".sm"):
        return parse_sm(file_path)

    elif file_path_lower.endswith(".xlsx") or file_path_lower.endswith(".xls"):
        return parse_excel(file_path)

    elif file_path_lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return parse_image(file_path)

    else:
        return {
            "type": "unknown",
            "error": "Неизвестный формат"
        }