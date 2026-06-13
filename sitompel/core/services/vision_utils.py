import cv2
import numpy as np
import os

def urutkan_titik(titik):
    """
    Mengurutkan 4 titik koordinat dari kontur.
    Urutan wajib: Kiri-Atas, Kanan-Atas, Kanan-Bawah, Kiri-Bawah.
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = titik.sum(axis=1)
    rect[0] = titik[np.argmin(s)] 
    rect[2] = titik[np.argmax(s)] 

    diff = np.diff(titik, axis=1)
    rect[1] = titik[np.argmin(diff)] 
    rect[3] = titik[np.argmax(diff)] 
    return rect

def proses_scan_kertas(path_gambar):
    """
    Membaca gambar mentah, mendeteksi tepi kertas ujian, meluruskannya,
    dan menimpa gambar aslinya dengan hasil potongan yang presisi.
    """
    # 1. Baca gambar dengan OpenCV
    img = cv2.imread(path_gambar)
    if img is None:
        raise ValueError("Gambar tidak dapat dibaca oleh mesin Vision.")

    ratio = img.shape[0] / 500.0
    img_asli = img.copy()
    img_resize = cv2.resize(img, (int(img.shape[1] / ratio), 500))

    # 2. Pre-processing: Grayscale, Blur, dan Deteksi Tepi (Canny)
    gray = cv2.cvtColor(img_resize, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(gray, 75, 200)

    # 3. Ekstraksi Kontur (Mencari garis luar kertas)
    cnts, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:5]
    kontur_kertas = None

    # 4. Validasi kontur yang memiliki tepat 4 sudut
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            kontur_kertas = approx
            break

    # Jika tidak ada kertas yang terdeteksi, biarkan gambar apa adanya
    if kontur_kertas is None:
        return path_gambar

    # 5. Transformasi Perspektif (Warping)
    rect = urutkan_titik(kontur_kertas.reshape(4, 2) * ratio)
    (tl, tr, br, bl) = rect

    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))

    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))

    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(img_asli, M, (maxWidth, maxHeight))

    # 6. Timpa gambar mentah dengan gambar hasil scan
    cv2.imwrite(path_gambar, warped)
    return path_gambar