from parsers.txt_parser import parse_txt
from parsers.docx_parser import parse_docx
from parsers.pdf_parser import parse_pdf
from parsers.sm_parser import parse_sm
from parsers.excel_parser import parse_excel

def read_file(file_path):
    file_path = file_path.lower()

    if file_path.endswith(".txt"):
        return parse_txt(file_path)

    elif file_path.endswith(".docx"):
        return parse_docx(file_path)

    elif file_path.endswith(".pdf"):
        return parse_pdf(file_path)

    elif file_path.endswith(".sm"):
        return parse_sm(file_path)

    elif file_path.endswith(".xlsx") or file_path.endswith(".xls"):
        return parse_excel(file_path)

    else:
        return "❌ Неизвестный формат файла"
