import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api.v1.endpoints.payments import owner_guard, payment_status, public_config, submit_claim, verify_claim, VerifyInput, PaymentStatusInput, qr_image
from app.db.base import Base
from app.models.payments import ActiveSubscription, OwnerPaymentConfig, PaymentClaim, SubscriptionTier


def run_without_event_loop(coroutine):
    """These route paths await only the no-upload branch; avoid Windows loopback sockets."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Test unexpectedly reached an asynchronous suspension point.")


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with testing_session() as session:
        session.add(OwnerPaymentConfig(id=1, upi_id="owner@bank", payee_name="Kisan Owner", updated_at=1))
        session.add_all([
            SubscriptionTier(tier_code="FREE", name="Free", price_inr=0, duration_days=36500, badge_color="#777", features_json="[]", is_active=True),
            SubscriptionTier(tier_code="PRO", name="Pro", price_inr=99, duration_days=30, badge_color="#377", features_json="[]", is_active=True),
        ])
        session.commit()
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_public_config_exposes_only_active_plans(db_session, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "enable_public_payment_claims", True)
    db_session.add(SubscriptionTier(tier_code="HIDDEN", name="Hidden", price_inr=1, duration_days=30,
                                    badge_color="#777", features_json="[]", is_active=False))
    db_session.commit()
    result = public_config(db_session)
    assert result["payments_ready"] is True
    assert result["upi_id"] == "owner@bank"
    assert [tier["tier_code"] for tier in result["tiers"]] == ["FREE", "PRO"]


def test_claim_rejects_duplicate_utr_and_approval_activates_plan(db_session, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "enable_public_payment_claims", True)
    first = run_without_event_loop(submit_claim(
        farmer_name="Demo Farmer", farmer_phone="9876543210", tier_code="PRO", utr_number="123456789012",
        screenshot=None, db=db_session,
    ))
    assert first["status"] == "PENDING"
    with pytest.raises(HTTPException) as duplicate:
        run_without_event_loop(submit_claim(
            farmer_name="Demo Farmer", farmer_phone="9876543210", tier_code="PRO", utr_number="123456789012",
            screenshot=None, db=db_session,
        ))
    assert duplicate.value.status_code == 409

    approved = verify_claim(VerifyInput(claim_id=first["claim_id"], decision="APPROVE"), db_session)
    assert approved["status"] == "APPROVED"
    subscription = db_session.get(ActiveSubscription, "9876543210")
    assert subscription is not None
    assert subscription.tier_code == "PRO"
    assert subscription.expires_at - subscription.activated_at == 30 * 86400
    assert payment_status(PaymentStatusInput(farmer_phone="9876543210", utr_number="123456789012"), db_session)["claim"]["status"] == "APPROVED"
    assert payment_status(PaymentStatusInput(farmer_phone="9876543210", utr_number="999999999999"), db_session)["claim"] is None
    assert db_session.query(PaymentClaim).one().utr_number == "123456789012"


def test_owner_routes_require_configured_pin(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "owner_pin", "owner-secret-123")
    monkeypatch.setattr(settings, "owner_email", "prathamesh.arc@gmail.com")
    request = Request({
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/api/v1/owner/dashboard", "raw_path": b"/api/v1/owner/dashboard",
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 8000),
        "server": ("testserver", 80),
    })
    with pytest.raises(HTTPException) as denied:
        owner_guard(request, "wrong-pin", "prathamesh.arc@gmail.com")
    assert denied.value.status_code == 401
    owner_guard(request, "owner-secret-123", "prathamesh.arc@gmail.com")
    with pytest.raises(HTTPException) as email_denied:
        owner_guard(request, "owner-secret-123", "someone-else@example.com")
    assert email_denied.value.status_code == 401


def test_public_payment_claims_are_disabled_by_default(db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_public_payment_claims", False)
    config = public_config(db_session)
    assert config["payments_ready"] is False
    assert config["payment_claims_enabled"] is False
    assert config["upi_id"] == ""
    with pytest.raises(HTTPException) as disabled:
        run_without_event_loop(submit_claim(
            farmer_name="Demo Farmer", farmer_phone="9876543210", tier_code="PRO", utr_number="123456789012",
            screenshot=None, db=db_session,
        ))
    assert disabled.value.status_code == 503
    assert db_session.query(PaymentClaim).count() == 0
    with pytest.raises(HTTPException) as status_disabled:
        payment_status(PaymentStatusInput(farmer_phone="9876543210", utr_number="123456789012"), db_session)
    assert status_disabled.value.status_code == 503
    with pytest.raises(HTTPException) as qr_disabled:
        qr_image(db_session)
    assert qr_disabled.value.status_code == 404

