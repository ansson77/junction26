"""Applicant profile rules that need no index, Gemini or database."""

from applicant import make_applicant_profile, skills_to_validate

SKILLS = [{"uri": u, "label": u, "skillType": "knowledge", "origin": "added"} for u in "abcd"]
QUESTIONS = {u: f"Q {u}?" for u in "abcd"}
ANSWERS = {u: f"A {u}" for u in "abcd"}


def test_top_two_by_points():
    assert skills_to_validate({"a": 1, "b": 5, "c": 3, "d": 1}) == ["b", "c"]


def test_ties_go_to_first_listed():
    assert skills_to_validate({"a": 2, "b": 3, "c": 3, "d": 2}) == ["b", "c"]
    assert skills_to_validate({"a": 2, "b": 2, "c": 2, "d": 2, "e": 2}) == ["a", "b"]


def test_single_skill_gets_one_question():
    assert skills_to_validate({"a": 10}) == ["a"]


def test_zero_point_skills_are_never_validated():
    assert skills_to_validate({"a": 0, "b": 10}) == ["b"]


def test_profile_keeps_questions_and_answers_only_for_top_skills():
    profile = make_applicant_profile(SKILLS, {"a": 1, "b": 5, "c": 3, "d": 1}, QUESTIONS, ANSWERS)
    kept = {s.uri: (s.validation_question, s.validation_answer) for s in profile.skills}
    assert kept == {"a": ("", ""), "b": ("Q b?", "A b"), "c": ("Q c?", "A c"), "d": ("", "")}
