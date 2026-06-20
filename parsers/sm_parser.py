def parse_sm(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return {
                "type": "smath",
                "text": f.read()
            }
    except:
        return {
            "type": "smath",
            "error": "Не удалось прочитать файл"
        }