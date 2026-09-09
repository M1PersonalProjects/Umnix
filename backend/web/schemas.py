from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class WebAppAuthRequest(BaseModel):
    init_data_raw: str


class WebAuthRequest(BaseModel):
    tg_id: int


class TelegramBotAuthStatusRequest(BaseModel):
    request_id: UUID
    browser_token: str = Field(..., min_length=32, max_length=128)


class FrontendErrorLogRequest(BaseModel):
    tg_id: Optional[int] = None
    message: str = Field(..., min_length=1, max_length=1000)
    source_file: str = Field(default="frontend", max_length=500)
    line_number: int = Field(default=0, ge=0, le=10_000_000)


class CancelTaskRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class TaskAttachmentOption(BaseModel):
    attachment_id: int
    use_as_ai_context: bool = True
    visible_to_student: bool = False


class ParentTaskRequest(BaseModel):
    student_ids: List[int] = Field(..., min_length=1, max_length=50)
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=40000)
    reference_answer: str = Field(default="", max_length=30000)
    subject: str = Field(default="Практика", max_length=150)
    topic: str = Field(default="", max_length=255)
    parent_comment: str = Field(default="", max_length=4000)
    ai_instructions: str = Field(default="", max_length=4000)
    book_id: Optional[int] = None
    page_id: Optional[int] = None
    attachment_ids: List[int] = Field(default_factory=list, max_length=10)
    send_files_to_student: bool = False
    attachment_options: List[TaskAttachmentOption] = Field(default_factory=list, max_length=10)
    context_mode: Optional[str] = None
    used_pages: List[Dict[str, Any]] = Field(default_factory=list)
    generated_items: List[Dict[str, Any]] = Field(default_factory=list, max_length=100, exclude=True)
    source_trace: List[Dict[str, Any]] = Field(default_factory=list, exclude=True)
    requested_count: int = Field(default=1, ge=1, le=100, exclude=True)


class ManualAnswerKeyGeneration(BaseModel):
    answer_text: str = Field(..., min_length=1, max_length=12000)
    answer_type: str = Field(default="exact", max_length=50)
    confidence: str = Field(default="high", max_length=20)
    ambiguity_note: str = Field(default="", max_length=2000)


class GenerateParentTaskRequest(BaseModel):
    student_ids: List[int] = Field(default_factory=list, max_length=50)
    topic: str = Field(..., min_length=2, max_length=300)
    parent_comment: str = Field(default="", max_length=4000)
    ai_instructions: str = Field(default="", max_length=4000)
    instructions: Optional[str] = Field(default=None, max_length=4000, exclude=True)
    book_id: Optional[int] = None
    page_id: Optional[int] = None
    attachment_ids: List[int] = Field(default_factory=list, max_length=10)
    send_files_to_student: bool = False
    task_count: int = Field(default=1, ge=1, le=100)


class TaskDraftPayload(BaseModel):
    student_ids: List[int] = Field(default_factory=list, max_length=50)
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=40000)
    reference_answer: str = Field(default="", max_length=30000)
    subject: str = Field(default="Практика", max_length=150)
    topic: str = Field(default="", max_length=255)
    parent_comment: str = Field(default="", max_length=4000)
    ai_instructions: str = Field(default="", max_length=4000)
    book_id: Optional[int] = None
    page_id: Optional[int] = None
    attachment_ids: List[int] = Field(default_factory=list, max_length=10)
    attachment_options: List[TaskAttachmentOption] = Field(default_factory=list, max_length=10)
    send_files_to_student: bool = False
    context_mode: Optional[str] = None
    used_pages: List[Dict[str, Any]] = Field(default_factory=list)
    generated_items: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)
    source_trace: List[Dict[str, Any]] = Field(default_factory=list)
    source_message_id: Optional[int] = None
    interactive_app_id: Optional[str] = None


class TaskReviewRequest(BaseModel):
    score: int = Field(..., ge=0, le=100)
    comment: str = Field(default="", max_length=4000)


class BookPayload(BaseModel):
    book_title: str = Field(..., min_length=2, max_length=246)
    book_program: str = Field(..., min_length=2, max_length=100)
    book_class: int = Field(..., ge=1, le=11)
    book_author: str = Field(default="", max_length=256)


class PagePayload(BaseModel):
    page_title: Optional[str] = Field(None, max_length=256)
    page_number: int = Field(..., ge=1)
    page_paragraph: Optional[str] = Field(None, max_length=100)
    page_text: str = ""
    page_html: str = ""
    page_markdown: str = ""


class OpenAITaskVerification(BaseModel):
    is_correct: bool = Field(..., description="True when the answer is correct.")
    explanation: str = Field(..., description="Short explanation for the teacher in Russian.")


class OpenAIPageResponse(BaseModel):
    page_title: str = Field(..., description="Meaningful visible topic title in Russian.")
    page_paragraph: str = Field(..., description="Section or paragraph title in Russian.")
    raw_text: str = Field(..., description="Full clean readable page text.")
    html_content: str = Field(..., description="Valid semantic HTML for the page.")
    markdown_content: str = Field(..., description="Clean Markdown without raw LaTeX syntax.")
