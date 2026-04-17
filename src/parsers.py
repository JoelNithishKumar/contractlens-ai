from __future__ import annotations

import io

import fitz
import streamlit as st
from docx import Document


@st.cache_data(show_spinner=False)
def extract_text_from_pdf_bytes(file_bytes: bytes) -> str:
    pdf = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []

    for page in pdf:
        text = page.get_text("text")
        if text:
            pages.append(text)

    return "\n".join(pages).strip()


@st.cache_data(show_spinner=False)
def extract_text_from_docx_bytes(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs).strip()


@st.cache_data(show_spinner=False)
def extract_text_from_txt_bytes(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="ignore").strip()


def extract_text_from_bytes(filename: str, file_bytes: bytes) -> str:
    lower = filename.lower()

    if lower.endswith(".pdf"):
        return extract_text_from_pdf_bytes(file_bytes)

    if lower.endswith(".docx"):
        return extract_text_from_docx_bytes(file_bytes)

    if lower.endswith(".txt"):
        return extract_text_from_txt_bytes(file_bytes)

    return ""