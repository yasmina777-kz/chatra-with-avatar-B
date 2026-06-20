import easyocr


reader = easyocr.Reader(['ru', 'en'], gpu=False)

def parse_image(file_path: str) -> dict:
    try:
        results = reader.readtext(file_path)


        text = "\n".join([item[1] for item in results])

        return {
            "type": "image",
            "text": text
        }

    except Exception as e:
        return {
            "type": "image",
            "text": "",
            "error": str(e)
        }