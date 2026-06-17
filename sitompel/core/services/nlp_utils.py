import logging, json, os, re
from sentence_transformers import SentenceTransformer, util
from google import genai
from django.conf import settings

# Set up logging untuk memantau load model di terminal
logger = logging.getLogger(__name__)

print("--> Memuat Model SBERT Multilingual ke dalam memori... (Ini hanya sekali saat server start)")
try:
    # Model diinisialisasi secara global agar tidak di-load berulang-ulang setiap ada request (In efisiensi memori)
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    print("--> Model SBERT Berhasil Dimuat!")
except Exception as e:
    logger.error(f"Gagal memuat model SBERT: {str(e)}")
    model = None

def hitung_skor_semantik(jawaban_mahasiswa, daftar_parameter_rubrik):
    """
    Menghitung kemiripan kosinus (Cosine Similarity) antara tulisan mahasiswa 
    dengan variasi kunci jawaban yang dibuat oleh dosen.
    Mengambil nilai kecocokan tertinggi.
    """
    if not jawaban_mahasiswa or not daftar_parameter_rubrik:
        return 0.0

    if not model:
        return _hitung_skor_lexical(jawaban_mahasiswa, daftar_parameter_rubrik)
        
    # Encode jawaban mahasiswa menjadi vektor numerik
    embedding_mahasiswa = model.encode(jawaban_mahasiswa, convert_to_tensor=True)
    
    skor_tertinggi = 0.0
    
    # Bandingkan jawaban mahasiswa dengan semua variasi argumen di parameter rubrik
    for parameter in daftar_parameter_rubrik:
        embedding_rubrik = model.encode(parameter.deskripsi_jawaban, convert_to_tensor=True)
        
        # Hitung Cosine Similarity menggunakan fungsi bawaan util SBERT
        kemiripan = util.cos_sim(embedding_mahasiswa, embedding_rubrik).item()
        
        if kemiripan > skor_tertinggi:
            skor_tertinggi = kemiripan
            
    # Nilai cosine similarity berkisar -1 hingga 1. 
    skor_bersih = max(0.0, min(1.0, skor_tertinggi))
    return skor_bersih


def _hitung_skor_lexical(jawaban_mahasiswa, daftar_parameter_rubrik):
    kata_jawaban = set(re.findall(r'\w+', jawaban_mahasiswa.lower()))
    if not kata_jawaban:
        return 0.0

    skor_tertinggi = 0.0
    for parameter in daftar_parameter_rubrik:
        kata_rubrik = set(re.findall(r'\w+', parameter.deskripsi_jawaban.lower()))
        if not kata_rubrik:
            continue
        overlap = len(kata_jawaban & kata_rubrik)
        skor = overlap / len(kata_rubrik)
        skor_tertinggi = max(skor_tertinggi, skor)

    return max(0.0, min(1.0, skor_tertinggi))

def validasi_logika(pertanyaan, teks_jawaban, parameter_rubrik, skor_sbert_mentah):
    """
    RAG LLM Validator: Mencegah 'keyword stuffing' dengan memahami logika bahasa.
    Menggunakan SDK google.genai terbaru.
    """
    acuan_rubrik = "\n".join([f"- {p.deskripsi_jawaban}" for p in parameter_rubrik])
    api_key = os.environ.get('GOOGLE_GENAI_API_KEY') or getattr(settings, 'GOOGLE_GENAI_API_KEY', '')

    if not api_key:
        return skor_sbert_mentah, "Nilai dihitung dari kemiripan SBERT. Google GenAI API key belum dikonfigurasi untuk validasi RAG."
    
    prompt = f"""
    Kamu adalah asisten Pengajar penilai ujian tulis berbasis esai.
    Pertanyaan Ujian: "{pertanyaan}"
    Kunci Jawaban/Rubrik Pengajar: 
    {acuan_rubrik}
    
    Jawaban Mahasiswa: "{teks_jawaban}"
    
    Sistem ekstraksi semantik (SBERT) memberikan skor awal kemiripan: {skor_sbert_mentah * 100}%.
    
    Tugasmu:
    1. Evaluasi apakah logika tata bahasa dari Jawaban Mahasiswa benar-benar selaras dengan Kunci Jawaban.
    2. Deteksi 'Keyword Stuffing': Jika mahasiswa menggunakan kata kunci yang sama tapi secara logika salah, ngawur, atau berlawanan dengan rubrik, berikan PENALTI BERAT (ubah skor menjadi di bawah 0.3).
    3. Jika logika mahasiswa benar dan menangkap esensi rubrik, pertahankan atau sesuaikan skor SBERT tersebut.
    4. Berikan skor akhir dalam rentang 0.0 hingga 1.0.
    5. Berikan maksimal 2 kalimat catatan alasan penilaianmu secara profesional untuk dosen.
    
    Output HARUS dalam format JSON murni persis seperti ini:
    {{"skor_akhir": 0.85, "catatan": "alasan di sini"}}
    """
    
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            json_str = match.group(0)
            data = json.loads(json_str)
            skor = float(data.get('skor_akhir', skor_sbert_mentah))
            catatan = data.get('catatan', 'Telah divalidasi oleh AI.')
            return skor, catatan
        else:
            return skor_sbert_mentah, "Format catatan LLM tidak sesuai."
            
    except Exception as e:
        print(f"Error LLM Baru: {e}")
        return skor_sbert_mentah, "Sistem RAG sedang sibuk. Nilai murni berdasarkan kemiripan SBERT."
