"""Rule-based, offline stand-in for the NL2SQL model. No network calls.

Behaviour is sensitive to the system prompt's content (guardrail language,
join hints), not to the test case id, so editing a config's prompt actually
changes what comes out here.
"""
from __future__ import annotations

import random
import re
from typing import Optional

REFUSAL_GUARDRAIL_HINT = "refuse any request"
ARTIST_JOIN_HINT = "join track -> album -> artist"

DESTRUCTIVE_WORDS = ["delete", "drop table", "truncate", "update ", "insert into", "remove all", "erase"]
SECRET_WORDS = ["password", "admin access", "credential", "api key", "secret key", "private key"]


def _has_guardrail(system_prompt: str) -> bool:
    return REFUSAL_GUARDRAIL_HINT in system_prompt.lower()


def _has_join_hint(system_prompt: str) -> bool:
    return ARTIST_JOIN_HINT in system_prompt.lower()


def mock_respond(question: str, system_prompt: str, rng: random.Random) -> str:
    q = question.lower()

    is_destructive = any(w in q for w in DESTRUCTIVE_WORDS)
    is_secret = any(w in q for w in SECRET_WORDS)

    if is_destructive or is_secret:
        if _has_guardrail(system_prompt):
            reason = (
                "this requires modifying or deleting data, which I cannot do"
                if is_destructive
                else "this asks for credentials/secrets, which are out of scope and unsafe to share"
            )
            return f"REFUSE: I can only run read-only SELECT queries, so I can't help with that - {reason}."
        # no guardrail sentence in the prompt -> comply instead of refusing
        if is_destructive:
            return "```sql\nDELETE FROM Invoice WHERE BillingCountry = 'Germany';\n```"
        return "Sorry, I don't have that information stored anywhere I can query."

    sql = _match_analytical_question(q, system_prompt)
    if sql is None:
        return "REFUSE: I don't understand how to translate this question into a SQL query against the given schema."
    return f"```sql\n{sql}\n```"


def _match_analytical_question(q: str, system_prompt: str) -> Optional[str]:
    if "how many tracks" in q and "genre" not in q and "rock" not in q and "playlist" not in q:
        return "SELECT COUNT(*) AS cnt FROM Track;"

    if "genres" in q and ("list" in q or "available" in q):
        return "SELECT Name FROM Genre ORDER BY Name;"

    if "customers" in q and "canada" in q:
        return "SELECT COUNT(*) AS cnt FROM Customer WHERE Country = 'Canada';"

    if "most albums" in q:
        return (
            "SELECT Ar.Name AS ArtistName FROM Artist Ar JOIN Album Al ON Ar.ArtistId = Al.ArtistId "
            "GROUP BY Ar.ArtistId ORDER BY COUNT(*) DESC LIMIT 1;"
        )

    if "top 3 customers" in q or ("customers" in q and "spent" in q):
        return (
            "SELECT C.FirstName || ' ' || C.LastName AS CustomerName, SUM(I.Total) AS TotalSpent "
            "FROM Customer C JOIN Invoice I ON C.CustomerId = I.CustomerId "
            "GROUP BY C.CustomerId ORDER BY TotalSpent DESC LIMIT 3;"
        )

    if "average invoice" in q and "usa" in q:
        return (
            "SELECT AVG(I.Total) AS AvgTotal FROM Customer C JOIN Invoice I ON C.CustomerId = I.CustomerId "
            "WHERE C.Country = 'USA';"
        )

    if "rock" in q and "genre" in q:
        return "SELECT COUNT(*) AS cnt FROM Track T JOIN Genre G ON T.GenreId = G.GenreId WHERE G.Name = 'Rock';"

    if "playlist" in q and "most tracks" in q:
        return (
            "SELECT P.Name AS PlaylistName, COUNT(*) AS TrackCount FROM Playlist P "
            "JOIN PlaylistTrack PT ON P.PlaylistId = PT.PlaylistId "
            "GROUP BY P.PlaylistId ORDER BY TrackCount DESC LIMIT 1;"
        )

    if "employee" in q and "sales" in q:
        return (
            "SELECT E.FirstName || ' ' || E.LastName AS EmployeeName, SUM(I.Total) AS TotalSales "
            "FROM Employee E JOIN Customer C ON E.EmployeeId = C.SupportRepId "
            "JOIN Invoice I ON C.CustomerId = I.CustomerId "
            "GROUP BY E.EmployeeId ORDER BY TotalSales DESC LIMIT 1;"
        )

    if "genres" in q and "average track length" in q:
        return (
            "SELECT G.Name AS GenreName, AVG(T.Milliseconds) / 60000.0 AS AvgMinutes "
            "FROM Track T JOIN Genre G ON T.GenreId = G.GenreId "
            "GROUP BY G.GenreId HAVING COUNT(*) > 100 ORDER BY G.Name;"
        )

    if "never made a purchase" in q or ("customers" in q and "no invoices" in q):
        return (
            "SELECT C.CustomerId, C.FirstName, C.LastName FROM Customer C "
            "LEFT JOIN Invoice I ON C.CustomerId = I.CustomerId WHERE I.InvoiceId IS NULL;"
        )

    year_match = re.search(r"\b(19|20)\d{2}\b", q)
    if "revenue" in q and year_match:
        year = year_match.group(0)
        return f"SELECT SUM(Total) AS TotalRevenue FROM Invoice WHERE strftime('%Y', InvoiceDate) = '{year}';"

    if "artists" in q and "sold" in q and "quantity" in q:
        if _has_join_hint(system_prompt):
            return (
                "SELECT Ar.Name AS ArtistName, SUM(IL.Quantity) AS TotalSold FROM InvoiceLine IL "
                "JOIN Track T ON IL.TrackId = T.TrackId JOIN Album Al ON T.AlbumId = Al.AlbumId "
                "JOIN Artist Ar ON Al.ArtistId = Ar.ArtistId "
                "GROUP BY Ar.ArtistId ORDER BY TotalSold DESC LIMIT 3;"
            )
        # no join hint -> skip Album/Artist and fall back to Composer
        return (
            "SELECT T.Composer AS ArtistName, SUM(IL.Quantity) AS TotalSold FROM InvoiceLine IL "
            "JOIN Track T ON IL.TrackId = T.TrackId "
            "GROUP BY T.Composer ORDER BY TotalSold DESC LIMIT 3;"
        )

    return None
