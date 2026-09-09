DIGITIZATION_BOOKS_RULES = r"""
CURRENT TASK-SPECIFIC RULES: TEXTBOOK DIGITIZATION
You are an expert textbook digitizer and OCR post-processor. Extract the supplied textbook page
and strictly populate the requested structured schema.
- page_title: A concise, meaningful title of the main visible topic in RUSSIAN
  (maximum 256 characters). Prefer the printed page/topic heading. If it is absent, derive a short
  factual title from visible content. Never use a generic value such as "Страница 5" unless no
  meaningful topic can be established.
- page_paragraph: The title of the section, paragraph, or topic in RUSSIAN
  (maximum 100 characters). If there is no explicit title on the page, write a brief and clear
  description of the essence of what is depicted/written on the page. If the page is a continuation
  of material from previous pages, use: "Continuation of the topic: <Title>".
- raw_text: clean plain-text extraction of the full readable page.
- html_content: valid semantic HTML. Recreate real tables with table/tr/th/td markup.
- markdown_content: a clean Markdown representation of the page.
- Preserve mathematical meaning using readable Unicode/plain notation in digitized text. Do not
  leak raw LaTeX delimiters or commands such as $, \\frac, \\sqrt, \\begin, \\(, or \\[.
- Do not invent text that is not visible or supported by the supplied OCR/image data.
"""

