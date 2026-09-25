"""Unmodified legacy payload contract and public response models."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, RootModel, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FeedbackActiveOptions(StrictModel):
    show_formulas: bool | None = Field(default=None, alias="showFormulas")
    color_atoms: bool | None = Field(default=None, alias="colorAtoms")
    spoken_language: bool | None = Field(default=None, alias="spokenLanguage")
    show_wrong_action_images: bool | None = Field(default=None, alias="showWrongActionImages")

    @model_validator(mode="after")
    def options_are_all_present_or_all_absent(self) -> FeedbackActiveOptions:
        expected = {
            "show_formulas",
            "color_atoms",
            "spoken_language",
            "show_wrong_action_images",
        }
        if self.model_fields_set and self.model_fields_set != expected:
            raise ValueError("Le opzioni attive devono essere complete oppure vuote")
        return self


class FeedbackInitialData(StrictModel):
    started_at: str = Field(alias="Tempo inizio esercitazione", max_length=64)
    total_time: str = Field(alias="Tempo totale", max_length=64)
    total_questions: int = Field(alias="Totale domande", ge=0, le=100)
    correct_questions: int = Field(alias="Totale domande corrette", ge=0, le=100)
    wrong_questions: int = Field(alias="Totale domande errate", ge=0, le=100)
    active_options: FeedbackActiveOptions = Field(alias="Opzioni attive")
    age: str | None = Field(default=None, alias="Età", min_length=1, max_length=3, pattern=r"^[0-9]{1,3}$")
    institution: str | None = Field(default=None, alias="Istituto di appartenenza", min_length=1, max_length=200)
    study_area: str | None = Field(default=None, alias="Indirizzo", min_length=1, max_length=100)

    @model_validator(mode="after")
    def totals_are_consistent(self) -> FeedbackInitialData:
        if self.correct_questions + self.wrong_questions != self.total_questions:
            raise ValueError("I totali delle domande non sono coerenti")
        return self


class FeedbackQuestionAnswer(StrictModel):
    question_type: str = Field(alias="Tipologia", min_length=1, max_length=128)
    elapsed: str = Field(alias="Tempo impiegato per rispondere", max_length=64)
    is_correct: Literal["Sì", "No"] = Field(alias="Risposta è corretta")
    question: str = Field(alias="Domanda", min_length=1, max_length=50_000)
    shown_answers: str = Field(alias="Risposte", max_length=100_000)
    selected_answer: str = Field(
        alias="Risposta utente",
        validation_alias=AliasChoices("Risposta utente", "Riposta utente"),
        max_length=50_000,
    )
    correct_answer: str = Field(
        alias="Risposta corretta",
        validation_alias=AliasChoices("Risposta corretta", "Riposta corretta"),
        max_length=50_000,
    )


class FeedbackQuestionEntry(RootModel[dict[str, FeedbackQuestionAnswer]]):
    model_config = ConfigDict(strict=True)

    @model_validator(mode="after")
    def has_one_numbered_question(self) -> FeedbackQuestionEntry:
        if len(self.root) != 1:
            raise ValueError("Ogni elemento deve contenere una sola domanda")
        key = next(iter(self.root))
        if re.fullmatch(r"Domanda nº (?:[1-9]|[1-9][0-9]|100)", key) is None:
            raise ValueError("Identificatore domanda non valido")
        return self


class FeedbackRatings(StrictModel):
    expectations: str = Field(alias="Aspettative test", pattern=r"^[1-5]$")
    aids_utility: str = Field(alias="Utilità ausili", pattern=r"^[1-5]$")
    lessons_utility: str = Field(alias="Utilità lezioni", pattern=r"^[1-5]$")
    test_difficulty: str = Field(alias="Difficoltà test", pattern=r"^[1-5]$")
    control: str = Field(alias="Controllo", pattern=r"^[1-5]$")


class FeedbackReport(StrictModel):
    """Validate the browser contract without using ``model_dump`` for storage."""

    initial_data: FeedbackInitialData = Field(alias="Initial Data")
    questions: list[FeedbackQuestionEntry] = Field(alias="Domande", max_length=100)
    feedback: FeedbackRatings = Field(alias="Feedback")

    @model_validator(mode="after")
    def report_is_consistent(self) -> FeedbackReport:
        if len(self.questions) != self.initial_data.total_questions:
            raise ValueError("Il numero di domande non coincide con il totale dichiarato")
        correct = 0
        for index, entry in enumerate(self.questions, start=1):
            expected_key = f"Domanda nº {index}"
            if expected_key not in entry.root:
                raise ValueError("La numerazione delle domande non e consecutiva")
            if entry.root[expected_key].is_correct == "Sì":
                correct += 1
        if correct != self.initial_data.correct_questions:
            raise ValueError("Il numero di risposte corrette non coincide con il totale dichiarato")
        return self


class FeedbackReceiptResponse(StrictModel):
    status: Literal["success"] = "success"
    filename: str = Field(pattern=r"^[0-9a-f-]{36}\.json$")
    receipt_id: UUID


class ChartManifestEntry(StrictModel):
    id: str
    category: str
    filename: str
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["ready", "insufficient_data"] = "ready"


class ChartManifest(StrictModel):
    schema_version: Literal[1] = 1
    generation_id: UUID
    generated_at: str
    session_count: int = Field(ge=2)
    charts: list[ChartManifestEntry]
