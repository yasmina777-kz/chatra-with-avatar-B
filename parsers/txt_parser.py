def parse_txt(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return {
            "type": "txt",
            "text": f.read()
        }