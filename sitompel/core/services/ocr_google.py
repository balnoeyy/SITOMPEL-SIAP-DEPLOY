import os
from google.cloud import vision
import io

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "kredensial-gcp.json"

def ekstrak_teks_dari_gambar(path_gambar_absolut):
    """
    Mengirim gambar ke Google Cloud Vision API dan mengembalikan teksnya.
    """
    client = vision.ImageAnnotatorClient()

    with io.open(path_gambar_absolut, 'rb') as image_file:
        content = image_file.read()

    image = vision.Image(content=content)
    
    # Memanggil fitur Document Text Detection (khusus untuk tulisan tangan/dokumen padat)
    response = client.document_text_detection(image=image)
    
    if response.error.message:
        raise Exception(f'Google Vision API Error: {response.error.message}')
        
    # Mengambil seluruh teks yang terdeteksi secara utuh
    if response.full_text_annotation:
        return response.full_text_annotation.text
    
    return ""