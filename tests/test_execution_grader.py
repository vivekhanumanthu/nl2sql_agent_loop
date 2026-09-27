from graders.execution_grader import grade_execution

DB = "data/chinook.db"


def test_matching_queries_pass():
    gold = "SELECT COUNT(*) AS cnt FROM Track;"
    agent = "SELECT COUNT(*) AS cnt FROM Track;"
    result = grade_execution(DB, agent, gold)
    assert result.passed


def test_mismatched_queries_fail():
    gold = "SELECT COUNT(*) AS cnt FROM Track;"
    agent = "SELECT COUNT(*) AS cnt FROM Genre;"
    result = grade_execution(DB, agent, gold)
    assert not result.passed


def test_destructive_sql_is_refused_by_executor():
    result = grade_execution(DB, "DELETE FROM Track;", "SELECT COUNT(*) AS cnt FROM Track;")
    assert not result.passed
    assert "refusing to execute" in result.error


def test_none_sql_fails_safely():
    result = grade_execution(DB, None, "SELECT COUNT(*) AS cnt FROM Track;")
    assert not result.passed


def test_unordered_row_sets_match_regardless_of_order():
    gold = "SELECT Name FROM Genre;"
    agent = "SELECT Name FROM Genre ORDER BY Name DESC;"
    result = grade_execution(DB, agent, gold)
    assert result.passed
