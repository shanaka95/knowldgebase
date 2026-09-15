"""Two pages can be summarised into the same question."""

from sqlmodel import Session

from app.models import SearchSuggestion
from app.services.suggestions import sample_for_user
from tests.utils.kb import create_document, create_namespace, create_user_with_password


def test_the_same_question_is_never_offered_twice(db: Session) -> None:
    """One row per document, but a form and its renewal summarise alike.

    Offering the same words twice is useless to read, and downstream it gave
    React two children with the same key - which it says plainly is
    unsupported, and which is how an omitted child becomes a crash elsewhere.
    """
    user, _ = create_user_with_password(db)
    ns = create_namespace(db, user)
    shared = "How do I renew the VPN token?"

    for _ in range(3):
        document = create_document(db, ns, user)
        db.add(
            SearchSuggestion(
                user_id=user.id,
                document_id=document.id,
                namespace_id=ns.id,
                question=shared,
            )
        )
    other = create_document(db, ns, user)
    db.add(
        SearchSuggestion(
            user_id=user.id,
            document_id=other.id,
            namespace_id=ns.id,
            question="What is the expenses limit?",
        )
    )
    db.commit()

    questions = [row.question for row in sample_for_user(db, user.id, limit=10)]
    assert len(questions) == len(set(questions)), questions
    assert sorted(questions) == sorted([shared, "What is the expenses limit?"])


def test_it_compares_the_way_a_reader_would(db: Session) -> None:
    """Spacing and case do not make it a different question."""
    user, _ = create_user_with_password(db)
    ns = create_namespace(db, user)
    for text in ("Where is the  handbook?", "where is the handbook?"):
        document = create_document(db, ns, user)
        db.add(
            SearchSuggestion(
                user_id=user.id,
                document_id=document.id,
                namespace_id=ns.id,
                question=text,
            )
        )
    db.commit()

    assert len(sample_for_user(db, user.id, limit=10)) == 1
