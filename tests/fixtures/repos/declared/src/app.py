"""A service with no schema files and no ORM tables. The data model is declared
out of band (repo notes/body), not derivable from code. Fixture for the honest
no-op: no schema artifact -> the gate does not false-alarm."""


def handle(request):
    return {"ok": True}
