"""Object buttons for ledger documents."""

from __future__ import annotations

from ....env import Env
from ....services.actions import object_action
from . import posting

MODEL = "accounting.move"


@object_action(MODEL, "action_post")
def post(env: Env, move_id: int):
    return posting.post(env, move_id)


@object_action(MODEL, "action_cancel")
def cancel(env: Env, move_id: int):
    return posting.cancel(env, move_id)


@object_action(MODEL, "action_reverse")
def reverse(env: Env, move_id: int):
    return posting.reverse(env, move_id)


@object_action(MODEL, "action_register_payment")
def register_payment(env: Env, move_id: int):
    from .payments import register_payment as register

    invoice = env["accounting.move"].read([move_id])[0]
    journal_ids = env["accounting.journal"].search([("code", "=", "BNK")], limit=1)
    if not journal_ids:
        journal_ids = env["accounting.journal"].search([], limit=1)
    return register(
        env,
        move_id,
        amount=invoice["amount_residual"] or invoice["amount_total"],
        journal_id=journal_ids[0],
    )


@object_action(MODEL, "action_credit_note")
def credit_note(env: Env, move_id: int):
    from .payments import create_credit_note

    return create_credit_note(env, move_id)


@object_action("accounting.payment", "action_cancel")
def cancel_payment(env: Env, payment_id: int):
    from .payments import cancel_payment as cancel

    return cancel(env, payment_id)


@object_action(MODEL, "action_secure")
def secure(env: Env, move_id: int):
    from .closing import secure as secure_entry

    return secure_entry(env, move_id)


@object_action(MODEL, "action_send_followup")
def send_followup(env: Env, move_id: int):
    from .closing import send_followup as followup

    return followup(env, move_id)


@object_action(MODEL, "action_generate_etims")
def generate_etims(env: Env, move_id: int):
    from .closing import generate_etims as generate

    return generate(env, move_id)


@object_action(MODEL, "action_write_off")
def write_off(env: Env, move_id: int):
    from .closing import write_off_invoice

    return write_off_invoice(env, move_id, received_amount=0)


@object_action("accounting.tax_return", "action_compute")
def compute_tax_return(env: Env, return_id: int):
    from .closing import compute_tax_return as compute

    return compute(env, return_id)


@object_action("accounting.asset", "action_compute")
def compute_asset(env: Env, asset_id: int):
    from .closing import compute_asset as compute

    return compute(env, asset_id)


@object_action("accounting.asset", "action_post_depreciation")
def post_depreciation(env: Env, asset_id: int):
    from .closing import post_depreciation as post_lines

    return post_lines(env, asset_id)


@object_action("accounting.loan", "action_compute")
def compute_loan(env: Env, loan_id: int):
    from .closing import compute_loan as compute

    return compute(env, loan_id)


@object_action("accounting.loan", "action_post_payments")
def post_loan(env: Env, loan_id: int):
    from .closing import post_loan as post_lines

    return post_lines(env, loan_id)


@object_action("accounting.deferral", "action_compute")
def compute_deferral(env: Env, deferral_id: int):
    from .closing import compute_deferral as compute

    return compute(env, deferral_id)


@object_action("accounting.deferral", "action_post")
def post_deferral(env: Env, deferral_id: int):
    from .closing import post_deferral as post_lines

    return post_lines(env, deferral_id)


@object_action("accounting.bank_statement", "action_import")
def import_statement(env: Env, statement_id: int):
    from .closing import import_statement as load

    return load(env, statement_id)


@object_action("accounting.bank_statement", "action_match")
def match_statement(env: Env, statement_id: int):
    from .closing import match_statement as match

    return match(env, statement_id)


@object_action("accounting.report", "action_run")
def run_report(env: Env, report_id: int):
    from .reporting import run

    return run(env, report_id)
