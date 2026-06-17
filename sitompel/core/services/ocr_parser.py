import re


def rapikan_teks_ocr(teks):
    lines = [line.strip() for line in (teks or '').replace('\r', '\n').split('\n')]
    lines = [line for line in lines if line]
    if not lines:
        return ''

    hasil = []
    buffer = []

    for line in lines:
        if _is_nomor_soal_line(line):
            if buffer:
                hasil.append(' '.join(buffer))
                buffer = []
            hasil.append(line)
            continue

        buffer.append(line)

    if buffer:
        hasil.append(' '.join(buffer))

    return '\n'.join(hasil).strip()


def pisahkan_jawaban_per_soal(teks_ocr, daftar_soal):
    nomor_soal = [soal.nomor_soal for soal in daftar_soal]
    nomor_valid = set(nomor_soal)
    hasil = {nomor: '' for nomor in nomor_soal}

    lines = [line.strip() for line in (teks_ocr or '').replace('\r', '\n').split('\n')]
    lines = [line for line in lines if line]
    nomor_aktif = None
    buffer = []
    pernah_menemukan_marker = False

    for line in lines:
        marker = _ambil_nomor_marker(line, nomor_valid)
        if marker:
            if nomor_aktif is not None:
                hasil[nomor_aktif] = _gabung_baris_jawaban(buffer)
            nomor_aktif, sisa_teks = marker
            buffer = [sisa_teks] if sisa_teks else []
            pernah_menemukan_marker = True
            continue

        if nomor_aktif is not None:
            buffer.append(line)

    if nomor_aktif is not None:
        hasil[nomor_aktif] = _gabung_baris_jawaban(buffer)

    if pernah_menemukan_marker:
        return hasil

    teks_rapi = rapikan_teks_ocr(teks_ocr)
    if len(nomor_soal) == 1:
        hasil[nomor_soal[0]] = teks_rapi
    return hasil


def _gabung_baris_jawaban(lines):
    cleaned = [line.strip() for line in lines if line and line.strip()]
    return ' '.join(cleaned).strip()


def _ambil_nomor_marker(line, nomor_valid):
    normalized = line.strip()

    patterns = [
        r'^(?:jawaban\s*)?(?:no(?:mor)?\.?\s*)?(\d{1,2})\s*[\.\):\-]\s*(.*)$',
        r'^(?:jawaban\s*)?(?:no(?:mor)?\.?\s*)?(\d{1,2})\s+(.+)$',
        r'^(?:jawaban\s*)?(?:no(?:mor)?\.?\s*)?(\d{1,2})$',
    ]

    for pattern in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            nomor = int(match.group(1))
            if nomor in nomor_valid:
                sisa_teks = match.group(2).strip() if len(match.groups()) > 1 else ''
                return nomor, sisa_teks

    return None


def _is_nomor_soal_line(line):
    return bool(re.match(r'^(?:jawaban\s*)?(?:no(?:mor)?\.?\s*)?\d{1,2}\s*[\.\):\-]?$', line, flags=re.IGNORECASE))
