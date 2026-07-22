"""Seed the rules table with Ontario RTA provisions and their embeddings.
Run from the backend/ directory with:  uv run python -m scripts.seed_rules
"""
from app.db import SessionLocal
from app.models import Rule
from app.embeddings import embed

RULES = [
    {"code": "ON-DEPOSIT-CAP", "title": "Rent deposit capped at one month",
     "description": "A rent deposit cannot exceed one month's rent or one rental period, whichever is less. It can only be applied to the last rental period and cannot be used as a damage deposit."},
    {"code": "ON-NO-EXTRA-DEPOSITS", "title": "No damage, pet, or other deposits",
     "description": "A landlord may only collect a last-month rent deposit and a refundable key deposit. Damage deposits, pet deposits, security deposits, and cleaning fees are not permitted."},
    {"code": "ON-NO-PET-BAN", "title": "Cannot prohibit pets",
     "description": "A tenancy agreement cannot prohibit animals or pets in the rental unit or around the building. No-pet clauses are void and unenforceable."},
    {"code": "ON-NO-GUEST-BAN", "title": "Cannot restrict guests",
     "description": "A landlord cannot stop a tenant from having guests, require notice or permission for guests, or charge extra fees or raise rent because of guests."},
    {"code": "ON-ENTRY-NOTICE", "title": "24 hours written notice to enter",
     "description": "A landlord may enter the unit only with at least 24 hours written notice, stating the reason and a time between 8 a.m. and 8 p.m., except in emergencies or with tenant consent."},
    {"code": "ON-NSF-CAP", "title": "NSF administration charge capped at $20",
     "description": "The landlord's administration charge for a returned or NSF cheque cannot be more than $20.00, plus any charges from the landlord's bank."},
    {"code": "ON-RENT-INCREASE-NOTICE", "title": "90 days notice, once per year",
     "description": "Rent can normally be increased only once every 12 months, with at least 90 days written notice, and by no more than the provincial rent increase guideline unless approved."},
    {"code": "ON-DEPOSIT-INTEREST", "title": "Interest owed on rent deposit",
     "description": "The landlord must pay the tenant interest on the rent deposit every year at the rent increase guideline rate."},
    {"code": "ON-NO-POSTDATED", "title": "Cannot require post-dated payment",
     "description": "A tenant cannot be required to pay rent by post-dated cheques or automatic payments, though they may choose to do so voluntarily."},
    {"code": "ON-SUBLET-CONSENT", "title": "Cannot unreasonably refuse sublet",
     "description": "A tenant may assign or sublet with the landlord's consent, and the landlord cannot arbitrarily or unreasonably withhold consent to a sublet or assignment."},
    {"code": "ON-LOCK-CHANGE", "title": "Locks cannot be changed without new keys",
     "description": "A landlord cannot change the locks of the rental unit unless they give the new keys to the tenant."},
    {"code": "ON-VITAL-SERVICES", "title": "Vital services cannot be shut off",
     "description": "A landlord cannot withhold or deliberately interfere with the reasonable supply of vital services such as heat, hot or cold water, electricity, fuel, or gas."},
]

def main() -> None:
    db = SessionLocal()
    try:
        texts = [f"{r['title']}. {r['description']}" for r in RULES]
        vectors = embed(texts)  # one batched API call for all rules
        db.query(Rule).delete()  # dev convenience: reset before reseeding
        for r, vec in zip(RULES, vectors):
            db.add(Rule(jurisdiction="ON", code=r["code"],
                        title=r["title"], description=r["description"],
                        embedding=vec))
        db.commit()
        print(f"Seeded {len(RULES)} rules.")
    finally:
        db.close()

if __name__ == "__main__":
    main()