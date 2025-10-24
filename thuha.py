import streamlit as st
import pandas as pd
import random
import re
import sqlite3
from datetime import datetime
import os
from gtts import gTTS
import tempfile
from deep_translator import GoogleTranslator

# Thêm thư viện xử lý file với import rõ ràng
try:
    import PyPDF2
    from docx import Document
except ImportError:
    PyPDF2 = None
    Document = None
    st.error("Vui lòng cài đặt thư viện: pip install PyPDF2 python-docx")

# Thêm jieba cho phân đoạn tiếng Trung
try:
    import jieba
except ImportError:
    jieba = None
    st.error("Vui lòng cài đặt thư viện: pip install jieba")


def init_database():
    """Khởi tạo database và xử lý migration"""
    conn = sqlite3.connect('learning_history.db', check_same_thread=False)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS learning_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  language TEXT,
                  word TEXT,
                  translation TEXT,
                  correct_count INTEGER DEFAULT 0,
                  wrong_count INTEGER DEFAULT 0,
                  last_reviewed TIMESTAMP,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS study_sessions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  language TEXT,
                  session_type TEXT,
                  score INTEGER,
                  total_questions INTEGER,
                  session_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Migration: Thêm cột language nếu chưa có
    # Cho learning_history
    c.execute("PRAGMA table_info(learning_history)")
    columns = [row[1] for row in c.fetchall()]
    if 'language' not in columns:
        c.execute("ALTER TABLE learning_history ADD COLUMN language TEXT")
        c.execute("UPDATE learning_history SET language = 'russian' WHERE language IS NULL")

    # Cho study_sessions
    c.execute("PRAGMA table_info(study_sessions)")
    columns = [row[1] for row in c.fetchall()]
    if 'language' not in columns:
        c.execute("ALTER TABLE study_sessions ADD COLUMN language TEXT")
        c.execute("UPDATE study_sessions SET language = 'russian' WHERE language IS NULL")

    conn.commit()
    conn.close()


def extract_text_from_pdf(file):
    """Trích xuất văn bản từ file PDF"""
    if PyPDF2 is None:
        st.error("PyPDF2 chưa được cài đặt!")
        return ""

    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception as e:
        st.error(f"Lỗi khi đọc file PDF: {str(e)}")
        return ""


def extract_text_from_docx(file):
    """Trích xuất văn bản từ file DOCX"""
    if Document is None:
        st.error("python-docx chưa được cài đặt!")
        return ""

    try:
        doc = Document(file)
        text = ""
        for paragraph in doc.paragraphs:
            if paragraph.text:
                text += paragraph.text + "\n"
        return text
    except Exception as e:
        st.error(f"Lỗi khi đọc file DOCX: {str(e)}")
        return ""


def extract_text_from_txt(file):
    """Trích xuất văn bản từ file TXT"""
    try:
        return file.read().decode('utf-8')
    except UnicodeDecodeError:
        # Thử decode với latin-1 nếu utf-8 fail
        file.seek(0)  # Reset file pointer
        return file.read().decode('latin-1')
    except Exception as e:
        st.error(f"Lỗi khi đọc file TXT: {str(e)}")
        return ""


def extract_words(language, text):
    """Trích xuất từ dựa trên ngôn ngữ"""
    if language == "russian":
        pattern = re.compile(r'[а-яА-ЯёЁ]{3,}')  # Ít nhất 3 ký tự cho tiếng Nga
        words = pattern.findall(text)
        # Lọc từ phổ biến (tùy chọn)
        common_words = ['и', 'в', 'на', 'с', 'по', 'у', 'о', 'к', 'но', 'а', 'из', 'от', 'до', 'для']
        filtered_words = [word for word in words if word.lower() not in common_words]
    elif language == "chinese":
        if jieba is None:
            st.error("jieba chưa được cài đặt!")
            return []
        # Sử dụng jieba để phân đoạn từ
        words = jieba.lcut(text)
        # Lọc chỉ giữ từ tiếng Trung, ít nhất 1 ký tự, và không phải từ phổ biến
        chinese_pattern = re.compile(r'^[\u4e00-\u9fff]+$')
        filtered_words = [word for word in words if chinese_pattern.match(word) and len(word) >= 1]
        # Lọc từ phổ biến (tùy chọn)
        common_words = ['的', '是', '在', '我', '有', '他', '这', '了', '你', '不', '和', '我们']
        filtered_words = [word for word in filtered_words if word not in common_words]
    else:
        return []

    return list(set(filtered_words))


def translate_words(language, words):
    """Dịch từ dựa trên ngôn ngữ sang tiếng Việt"""
    translations = {}

    if not words:
        return translations

    progress_bar = st.progress(0)
    status_text = st.empty()

    # Khởi tạo translator
    source_lang = 'ru' if language == "russian" else 'zh-CN'
    translator = GoogleTranslator(source=source_lang, target='vi')

    for i, word in enumerate(words):
        try:
            # Dùng deep-translator
            translated_text = translator.translate(word)
            translations[word] = translated_text
        except Exception as e:
            st.warning(f"Không thể dịch từ '{word}': {str(e)}")
            translations[word] = f"Chưa dịch được: {word}"

        progress_bar.progress((i + 1) / len(words))
        status_text.text(f"Đang dịch... {i + 1}/{len(words)} từ")

    status_text.text("✅ Hoàn thành dịch thuật!")
    return translations


def save_to_history(language, word, translation, is_correct=True):
    """Lưu từ vào lịch sử học tập"""
    conn = sqlite3.connect('learning_history.db', check_same_thread=False)
    c = conn.cursor()

    # Kiểm tra xem từ đã tồn tại chưa (dựa trên ngôn ngữ)
    c.execute('SELECT * FROM learning_history WHERE language = ? AND word = ?', (language, word))
    existing = c.fetchone()

    if existing:
        if is_correct:
            c.execute('''UPDATE learning_history 
                        SET correct_count = correct_count + 1, last_reviewed = ?
                        WHERE language = ? AND word = ?''', (datetime.now(), language, word))
        else:
            c.execute('''UPDATE learning_history 
                        SET wrong_count = wrong_count + 1, last_reviewed = ?
                        WHERE language = ? AND word = ?''', (datetime.now(), language, word))
    else:
        c.execute('''INSERT INTO learning_history 
                    (language, word, translation, correct_count, wrong_count, last_reviewed)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                  (language, word, translation, 1 if is_correct else 0, 0 if is_correct else 1, datetime.now()))

    conn.commit()
    conn.close()


def save_study_session(language, session_type, score, total_questions):
    """Lưu session học tập"""
    conn = sqlite3.connect('learning_history.db', check_same_thread=False)
    c = conn.cursor()

    c.execute('''INSERT INTO study_sessions 
                (language, session_type, score, total_questions)
                VALUES (?, ?, ?, ?)''',
              (language, session_type, score, total_questions))

    conn.commit()
    conn.close()


def get_learning_stats(language):
    """Lấy thống kê học tập dựa trên ngôn ngữ"""
    conn = sqlite3.connect('learning_history.db', check_same_thread=False)
    c = conn.cursor()

    c.execute('''SELECT 
                 COUNT(*) as total_words,
                 SUM(correct_count) as total_correct,
                 SUM(wrong_count) as total_wrong,
                 COUNT(CASE WHEN correct_count > wrong_count THEN 1 END) as mastered_words
                 FROM learning_history
                 WHERE language = ?''', (language,))

    stats = c.fetchone()
    conn.close()

    return {
        'total_words': stats[0] or 0,
        'total_correct': stats[1] or 0,
        'total_wrong': stats[2] or 0,
        'mastered_words': stats[3] or 0
    }


def text_to_speech(text, lang='ru'):
    """Chuyển văn bản thành giọng nói"""
    try:
        tts = gTTS(text=text, lang=lang.lower(), slow=False)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
            tts.save(fp.name)
            return fp.name
    except Exception as e:
        st.error(f"Lỗi phát âm: {str(e)}")
        return None


def create_quiz(translations, num_questions=20):  # Đã thay đổi từ 10 lên 20
    """Tạo câu hỏi trắc nghiệm"""
    quiz = []
    words = list(translations.keys())

    if len(words) < 4:
        st.warning("Cần ít nhất 4 từ để tạo quiz!")
        return quiz

    for _ in range(min(num_questions, len(words))):
        correct_word = random.choice(words)
        correct_answer = translations[correct_word]

        # Tạo các đáp án sai
        wrong_answers = []
        while len(wrong_answers) < 3:
            wrong_word = random.choice(words)
            if (wrong_word != correct_word and
                    translations[wrong_word] not in wrong_answers and
                    translations[wrong_word] != correct_answer):
                wrong_answers.append(translations[wrong_word])

        # Trộn đáp án
        options = wrong_answers + [correct_answer]
        random.shuffle(options)

        quiz.append({
            'question': f"Từ '{correct_word}' có nghĩa là gì?",
            'options': options,
            'correct_answer': correct_answer,
            'word': correct_word  # Đổi tên từ 'russian_word' thành 'word' để chung
        })

    return quiz


def flashcard_view(language, translations):
    """Hiển thị chế độ flashcard"""
    st.subheader("📇 Flashcards")

    if not translations:
        st.warning("Chưa có từ vựng. Hãy upload file để bắt đầu!")
        return

    # Khởi tạo session state cho flashcard
    if 'flashcard_index' not in st.session_state:
        st.session_state.flashcard_index = 0
    if 'show_translation' not in st.session_state:
        st.session_state.show_translation = False
    if 'known_words' not in st.session_state:
        st.session_state.known_words = set()

    words = list(translations.keys())
    current_index = st.session_state.flashcard_index
    current_word = words[current_index]
    current_translation = translations[current_word]

    # Hiển thị flashcard với giao diện đẹp hơn
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        # Flashcard container với CSS đẹp hơn
        st.markdown(f"""
        <div style='
            border: 2px solid #4CAF50; 
            border-radius: 15px; 
            padding: 60px 40px; 
            text-align: center; 
            background: linear-gradient(135deg, #f9f9f9 0%, #e8f5e8 100%);
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
            margin: 20px 0;
            min-height: 250px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        '>
            <h1 style='color: #2E7D32; font-size: 2.8em; margin-bottom: 20px;'>{current_word}</h1>
            {f"<h2 style='color: #4CAF50; font-size: 2.2em; margin-top: 20px;'>{current_translation}</h2>" if st.session_state.show_translation else ""}
        </div>
        """, unsafe_allow_html=True)

        # Nút điều khiển với styling đẹp hơn
        col_btn1, col_btn2, col_btn3 = st.columns(3)

        with col_btn1:
            if st.button("🔄 Lật thẻ", use_container_width=True, type="primary"):
                st.session_state.show_translation = not st.session_state.show_translation
                st.rerun()

        with col_btn2:
            if st.button("✅ Đã biết", use_container_width=True, type="secondary"):
                st.session_state.known_words.add(current_word)
                save_to_history(language, current_word, current_translation, True)
                st.success("Đã đánh dấu là đã biết!")
                st.rerun()

        with col_btn3:
            lang_code = 'ru' if language == "russian" else 'zh-CN'
            if st.button("🔊 Phát âm", use_container_width=True):
                audio_file = text_to_speech(current_word, lang_code)
                if audio_file:
                    st.audio(audio_file, format='audio/mp3')
                    os.unlink(audio_file)  # Xóa file tạm

        # Điều hướng với styling đẹp hơn
        col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
        with col_nav1:
            if st.button("⏮ Trước", use_container_width=True, disabled=current_index == 0):
                if current_index > 0:
                    st.session_state.flashcard_index -= 1
                    st.session_state.show_translation = False
                    st.rerun()

        with col_nav2:
            st.markdown(
                f"<div style='text-align: center; padding: 10px;'><strong>Thẻ {current_index + 1} / {len(words)}</strong></div>",
                unsafe_allow_html=True)
            progress = (current_index + 1) / len(words)
            st.progress(progress)

        with col_nav3:
            if st.button("Tiếp ⏭", use_container_width=True, disabled=current_index == len(words) - 1):
                if current_index < len(words) - 1:
                    st.session_state.flashcard_index += 1
                    st.session_state.show_translation = False
                    st.rerun()

        # Thống kê với styling đẹp hơn
        st.markdown(f"""
        <div style='
            background: #e8f5e8; 
            padding: 15px; 
            border-radius: 10px; 
            margin: 15px 0;
            text-align: center;
            border-left: 5px solid #4CAF50;
        '>
            <strong>📊 Đã biết: {len(st.session_state.known_words)} / {len(words)} từ</strong>
        </div>
        """, unsafe_allow_html=True)


def main():
    # Khởi tạo database
    init_database()

    st.set_page_config(
        page_title="Thu Hà sai đẹp giếu",
        page_icon="🌍",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Custom CSS để cải thiện giao diện
    st.markdown("""
    <style>
    .main-header {
        font-size: 3rem;
        color: #2E7D32;
        text-align: center;
        margin-bottom: 2rem;
        font-weight: bold;
    }
    .metric-card {
        background: linear-gradient(135deg, #f8fffe 0%, #e3f2fd 100%);
        padding: 20px;
        border-radius: 15px;
        border-left: 5px solid #4CAF50;
        margin: 10px 0;
    }
    .stButton button {
        border-radius: 10px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }
    .quiz-question {
        background: #f8f9fa;
        padding: 20px;
        border-radius: 10px;
        margin: 15px 0;
        border-left: 4px solid #2196F3;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="main-header">🌍 HỌC NGOẠI NGỮ VỚI HÀ NHÉEE!!!</div>', unsafe_allow_html=True)
    st.markdown("### Upload tài liệu PDF/DOCX/TXT để tạo quiz và flashcards học từ vựng!")

    # Sidebar cho điều hướng và chọn ngôn ngữ
    with st.sidebar:
        st.markdown("## 🎯 Điều hướng")

        # Chọn ngôn ngữ với styling đẹp hơn
        language = st.selectbox(
            "**Chọn ngôn ngữ**",
            ["russian", "chinese"],
            format_func=lambda x: "🇷🇺 Tiếng Nga" if x == "russian" else "🇨🇳 Tiếng Trung",
            key="language_select"
        )

        app_mode = st.selectbox(
            "**Chọn chế độ**",
            ["📤 Upload Tài liệu", "🎯 Làm Quiz", "📇 Flashcards", "📊 Lịch sử Học tập", "📚 Từ vựng Đã lưu"],
            key="app_mode_select"
        )

        st.markdown("---")

        # Hiển thị thống kê nhanh trong sidebar với styling đẹp hơn
        st.markdown("### 📈 Thống kê học tập")
        stats = get_learning_stats(language)

        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size: 1.2em; color: #2E7D32;">📚 Tổng từ</div>
            <div style="font-size: 2em; font-weight: bold; color: #1B5E20;">{stats['total_words']}</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size: 1.2em; color: #2E7D32;">✅ Đã thuộc</div>
            <div style="font-size: 2em; font-weight: bold; color: #1B5E20;">{stats['mastered_words']}</div>
        </div>
        """, unsafe_allow_html=True)

        accuracy = stats['total_correct'] / (stats['total_correct'] + stats['total_wrong']) * 100 if (stats[
                                                                                                          'total_correct'] +
                                                                                                      stats[
                                                                                                          'total_wrong']) > 0 else 0
        accuracy_color = "#4CAF50" if accuracy >= 70 else "#FF9800" if accuracy >= 50 else "#F44336"

        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size: 1.2em; color: #2E7D32;">🎯 Tỷ lệ đúng</div>
            <div style="font-size: 2em; font-weight: bold; color: {accuracy_color};">{accuracy:.1f}%</div>
        </div>
        """, unsafe_allow_html=True)

    # Khởi tạo session state cho translations dựa trên ngôn ngữ
    session_key = f'translations_{language}'
    if session_key not in st.session_state:
        st.session_state[session_key] = {}

    translations = st.session_state[session_key]

    # Chế độ Upload Tài liệu
    if app_mode == "📤 Upload Tài liệu":
        lang_display = "Tiếng Nga" if language == "russian" else "Tiếng Trung"
        st.header(f"📤 Upload Tài liệu {lang_display}")

        # Upload file với container đẹp hơn
        with st.container():
            st.markdown("### 📁 Chọn file văn bản")
            uploaded_file = st.file_uploader(
                f"Kéo thả file hoặc click để chọn file {lang_display}",
                type=['pdf', 'docx', 'txt'],
                help="Hỗ trợ PDF, DOCX, và TXT",
                label_visibility="collapsed"
            )

        if uploaded_file is not None:
            # Hiển thị thông tin file trong card đẹp
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <div>📄 Tên file</div>
                    <div style="font-weight: bold; font-size: 1.1em;">{uploaded_file.name}</div>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                st.markdown(f"""
                <div class="metric-card">
                    <div>📊 Loại file</div>
                    <div style="font-weight: bold; font-size: 1.1em;">{uploaded_file.type}</div>
                </div>
                """, unsafe_allow_html=True)
            with col3:
                st.markdown(f"""
                <div class="metric-card">
                    <div>💾 Kích thước</div>
                    <div style="font-weight: bold; font-size: 1.1em;">{uploaded_file.size / 1024:.1f} KB</div>
                </div>
                """, unsafe_allow_html=True)

            # Đọc file dựa trên loại
            with st.spinner("🔄 Đang đọc và xử lý file..."):
                if uploaded_file.type == "application/pdf":
                    text = extract_text_from_pdf(uploaded_file)
                elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                    text = extract_text_from_docx(uploaded_file)
                else:
                    text = extract_text_from_txt(uploaded_file)

            if text:
                st.success("✅ Đã đọc file thành công!")

                # Hiển thị preview văn bản
                with st.expander("👀 Xem trước văn bản", expanded=False):
                    preview_text = text[:1000] + "..." if len(text) > 1000 else text
                    st.text_area("Nội dung văn bản", preview_text, height=200, key="preview",
                                 label_visibility="collapsed")

                # Trích xuất và dịch từ vựng
                with st.spinner("🔍 Đang trích xuất và dịch từ vựng..."):
                    words = extract_words(language, text)

                    if not words:
                        st.error(f"❌ Không tìm thấy từ {lang_display} trong văn bản!")
                        return

                    st.info(f"📖 Tìm thấy {len(words)} từ {lang_display}")

                    # Dịch từ
                    st.session_state[session_key] = translate_words(language, words)

                # Hiển thị kết quả
                st.subheader("📚 Từ vựng đã trích xuất")
                vocab_df = pd.DataFrame(
                    list(st.session_state[session_key].items()),
                    columns=[lang_display, 'Tiếng Việt']
                )
                st.dataframe(vocab_df, use_container_width=True)

                # Tùy chọn tải xuống từ vựng
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    csv = vocab_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Tải xuống từ vựng (CSV)",
                        data=csv,
                        file_name=f"{language}_vocabulary.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                with col_dl2:
                    if st.button("🎯 Chuyển sang làm Quiz ngay", use_container_width=True):
                        st.session_state.app_mode_select = "🎯 Làm Quiz"
                        st.rerun()

    # Chế độ Làm Quiz
    elif app_mode == "🎯 Làm Quiz":
        st.header("🎯 Làm Quiz Kiểm tra Từ vựng")

        if not translations:
            st.warning("⚠️ Vui lòng upload tài liệu trước!")
            st.info("💡 Hãy chuyển sang tab '📤 Upload Tài liệu' để upload file và trích xuất từ vựng.")
            return

        # Cài đặt quiz
        with st.container():
            st.markdown("### ⚙️ Cài đặt Quiz")
            col_set1, col_set2 = st.columns(2)
            with col_set1:
                num_questions = st.slider(
                    "Số câu hỏi:",
                    min_value=5,
                    max_value=min(30, len(translations)),
                    value=20,  # Mặc định 20 câu
                    help=f"Tối đa {min(30, len(translations))} câu từ {len(translations)} từ có sẵn"
                )
            with col_set2:
                st.markdown(f"""
                <div style='background: #e3f2fd; padding: 15px; border-radius: 10px; margin-top: 10px;'>
                    <strong>📊 Thông tin:</strong><br>
                    • Từ có sẵn: {len(translations)}<br>
                    • Số câu tối đa: {min(30, len(translations))}
                </div>
                """, unsafe_allow_html=True)

        quiz_key = f'quiz_{language}'

        # Nút tạo quiz mới
        if st.button("🎲 Tạo Quiz Mới", type="primary", use_container_width=True):
            st.session_state[quiz_key] = create_quiz(translations, num_questions)
            st.session_state[f'quiz_answers_{language}'] = [None] * len(st.session_state[quiz_key])
            st.session_state[f'quiz_submitted_{language}'] = False
            st.success(f"✅ Đã tạo quiz {len(st.session_state[quiz_key])} câu!")
            st.rerun()

        if quiz_key in st.session_state and st.session_state[quiz_key]:
            st.markdown("---")
            st.subheader(f"📝 Bài Quiz ({len(st.session_state[quiz_key])} câu)")

            # Hiển thị từng câu hỏi
            for i, q in enumerate(st.session_state[quiz_key]):
                st.markdown(f'<div class="quiz-question">', unsafe_allow_html=True)

                # Câu hỏi và nút phát âm
                col_q, col_audio = st.columns([4, 1])
                with col_q:
                    st.write(f"**Câu {i + 1}: {q['question']}**")
                with col_audio:
                    lang_code = 'ru' if language == "russian" else 'zh-CN'
                    if st.button(f"🔊", key=f"audio_{language}_{i}", use_container_width=True):
                        audio_file = text_to_speech(q['word'], lang_code)
                        if audio_file:
                            st.audio(audio_file, format='audio/mp3')
                            os.unlink(audio_file)

                # Đáp án
                user_answer = st.radio(
                    f"Chọn đáp án cho câu {i + 1}:",
                    q['options'],
                    key=f"quiz_{language}_{i}",
                    index=st.session_state[f'quiz_answers_{language}'][i] if
                    st.session_state[f'quiz_answers_{language}'][i] is not None else 0
                )
                st.session_state[f'quiz_answers_{language}'][i] = q['options'].index(user_answer)

                st.markdown('</div>', unsafe_allow_html=True)

            # Nút nộp bài
            col_submit1, col_submit2 = st.columns([1, 1])
            with col_submit1:
                if st.button("📤 Nộp Bài", type="primary", use_container_width=True):
                    score = 0
                    for i, q in enumerate(st.session_state[quiz_key]):
                        user_answer = q['options'][st.session_state[f'quiz_answers_{language}'][i]]
                        if user_answer == q['correct_answer']:
                            score += 1
                            save_to_history(language, q['word'], q['correct_answer'], True)
                        else:
                            save_to_history(language, q['word'], q['correct_answer'], False)

                    st.session_state[f'quiz_submitted_{language}'] = True
                    save_study_session(language, "quiz", score, len(st.session_state[quiz_key]))

                    # Hiển thị kết quả
                    st.success(f"🎉 Điểm của bạn: **{score}/{len(st.session_state[quiz_key])}**")

                    # Hiển thị kết quả chi tiết
                    with st.expander("📋 Xem chi tiết đáp án", expanded=True):
                        for i, q in enumerate(st.session_state[quiz_key]):
                            user_answer = q['options'][st.session_state[f'quiz_answers_{language}'][i]]
                            is_correct = user_answer == q['correct_answer']

                            if is_correct:
                                st.write(f"✅ **Câu {i + 1}:** {q['correct_answer']}")
                            else:
                                st.write(
                                    f"❌ **Câu {i + 1}:** Đáp án của bạn: `{user_answer}` | Đáp án đúng: `{q['correct_answer']}`")

            with col_submit2:
                if st.button("🔄 Làm Lại Quiz", use_container_width=True):
                    st.session_state[quiz_key] = create_quiz(translations, num_questions)
                    st.session_state[f'quiz_answers_{language}'] = [None] * len(st.session_state[quiz_key])
                    st.session_state[f'quiz_submitted_{language}'] = False
                    st.rerun()

        elif quiz_key in st.session_state:
            st.warning("❌ Không đủ từ để tạo quiz! Cần ít nhất 4 từ.")

    # Chế độ Flashcards
    elif app_mode == "📇 Flashcards":
        flashcard_view(language, translations)

    # Chế độ Lịch sử Học tập
    elif app_mode == "📊 Lịch sử Học tập":
        st.header("📊 Lịch sử Học tập")

        conn = sqlite3.connect('learning_history.db', check_same_thread=False)

        # Thống kê tổng quan với card đẹp
        stats = get_learning_stats(language)
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <div style="font-size: 1.1em;">📚 Tổng số từ</div>
                <div style="font-size: 2em; font-weight: bold; color: #2E7D32;">{stats['total_words']}</div>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown(f"""
            <div class="metric-card">
                <div style="font-size: 1.1em;">✅ Từ đã thuộc</div>
                <div style="font-size: 2em; font-weight: bold; color: #2E7D32;">{stats['mastered_words']}</div>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            st.markdown(f"""
            <div class="metric-card">
                <div style="font-size: 1.1em;">🎯 Số câu đúng</div>
                <div style="font-size: 2em; font-weight: bold; color: #2E7D32;">{stats['total_correct']}</div>
            </div>
            """, unsafe_allow_html=True)
        with col4:
            accuracy = stats['total_correct'] / (stats['total_correct'] + stats['total_wrong']) * 100 if (stats[
                                                                                                              'total_correct'] +
                                                                                                          stats[
                                                                                                              'total_wrong']) > 0 else 0
            accuracy_color = "#4CAF50" if accuracy >= 70 else "#FF9800" if accuracy >= 50 else "#F44336"
            st.markdown(f"""
            <div class="metric-card">
                <div style="font-size: 1.1em;">📈 Tỷ lệ đúng</div>
                <div style="font-size: 2em; font-weight: bold; color: {accuracy_color};">{accuracy:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)

        # Lịch sử học tập chi tiết
        st.subheader("📋 Chi tiết học tập")
        history_df = pd.read_sql_query('''
            SELECT word, translation, correct_count, wrong_count, 
                   last_reviewed, 
                   CASE WHEN (correct_count + wrong_count) > 0 
                        THEN ROUND(correct_count * 100.0 / (correct_count + wrong_count), 1) 
                        ELSE 0 END as accuracy
            FROM learning_history 
            WHERE language = ?
            ORDER BY last_reviewed DESC
        ''', conn, params=(language,))

        if not history_df.empty:
            st.dataframe(history_df, use_container_width=True)

            # Từ cần ôn tập (tỷ lệ đúng < 50%)
            weak_words = history_df[history_df['accuracy'] < 50]
            if not weak_words.empty:
                st.subheader("📝 Từ cần ôn tập")
                st.dataframe(weak_words[['word', 'translation', 'accuracy']], use_container_width=True)

                # Nút ôn tập từ yếu
                if st.button("🔄 Ôn Tập Từ Cần Cải Thiện", use_container_width=True):
                    review_translations = dict(zip(weak_words['word'], weak_words['translation']))
                    st.session_state[f'translations_{language}'] = review_translations
                    st.session_state.app_mode_select = "📇 Flashcards"
                    st.success(f"Đã chọn {len(weak_words)} từ cần ôn tập!")
                    st.rerun()
        else:
            st.info("📝 Chưa có lịch sử học tập.")

        conn.close()

    # Chế độ Từ vựng Đã lưu
    elif app_mode == "📚 Từ vựng Đã lưu":
        st.header("📚 Từ vựng Đã lưu")

        conn = sqlite3.connect('learning_history.db', check_same_thread=False)
        saved_words_df = pd.read_sql_query('''
            SELECT word, translation, correct_count, wrong_count, last_reviewed
            FROM learning_history 
            WHERE language = ?
            ORDER BY correct_count DESC, last_reviewed DESC
        ''', conn, params=(language,))

        if not saved_words_df.empty:
            st.dataframe(saved_words_df, use_container_width=True)

            # Ôn tập nhanh
            st.subheader("🔄 Ôn tập nhanh")
            col_rev1, col_rev2 = st.columns(2)

            with col_rev1:
                if st.button("🎯 Ôn tập ngẫu nhiên 10 từ", use_container_width=True):
                    review_words = saved_words_df.sample(min(10, len(saved_words_df)))
                    st.session_state[f'translations_{language}'] = dict(
                        zip(review_words['word'], review_words['translation']))
                    st.session_state.app_mode_select = "📇 Flashcards"
                    st.success(f"✅ Đã chọn {len(review_words)} từ để ôn tập!")
                    st.rerun()

            with col_rev2:
                if st.button("📖 Ôn tập tất cả từ", use_container_width=True):
                    st.session_state[f'translations_{language}'] = dict(
                        zip(saved_words_df['word'], saved_words_df['translation']))
                    st.session_state.app_mode_select = "📇 Flashcards"
                    st.success(f"✅ Đã chọn {len(saved_words_df)} từ để ôn tập!")
                    st.rerun()
        else:
            st.info("📝 Chưa có từ vựng nào được lưu.")

        conn.close()


if __name__ == "__main__":
    main()