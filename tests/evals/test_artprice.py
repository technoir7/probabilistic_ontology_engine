"""Artprice's yearly Top 500 artists by auction turnover, read from its free
report PDFs (abductive_engine ART-PLAN §12.7)."""
from evals.artprice import Row, key, parse_row, table


def test_rows_of_the_recent_layout_give_rank_name_birth_and_turnover():
    assert parse_row("51 Ernst Ludwig KIRCHNER (1880-1938) Germany $26,623,340 227 146 $7,517,690") == \
        Row(51, "Ernst Ludwig KIRCHNER", 1880, 26_623_340)
    assert parse_row("56 Cecily BROWN (b.1969) United Kingdom $23,403,290 28 5 $5,979,000") == \
        Row(56, "Cecily BROWN", 1969, 23_403_290)
    assert parse_row("68 WARHOL & BASQUIAT (XX) United States $19,379,110 9 1 $19,367,500 X").born is None
    assert parse_row("63 SAN Yu (1895/1901-1966) China $20,785,280 48 24 $5,499,290").born == 1895


def test_rows_of_the_older_layouts_skip_last_years_rank_and_read_unprefixed_figures():
    assert parse_row("401 149 sAInt-PHALLe de niki (1930-2002) 2,866,064 4,558,371 159 125 463,420 661,14 4") == \
        Row(401, "sAInt-PHALLe de niki", 1930, 2_866_064)
    assert parse_row("2 PiCaSSO Pablo (1881-1973) 375,054,326 2,898 28,000,000") == Row(2, "PiCaSSO Pablo", 1881, 375_054_326)
    assert parse_row("403 5360 LI Guijun (1964) 2,845,495 63,360 11 2 615,820 44,010").born == 1964


def test_lines_that_are_not_clean_rows_are_refused_not_guessed():
    assert parse_row("1 WarhOL andy (1928-1987) 5 6 9, 5 07, 0 8 3 1,394 73,000,000") is None   # digits broken apart
    assert parse_row("2 Sotheby's $3,589,239,300 14,134") is None                               # an auction house
    assert parse_row("3 Excluding antiques, furniture and objects.") is None


def test_a_table_keeps_only_falling_turnover_and_not_a_shorter_ranking_before_it():
    text = "\n".join([
        "TOP 10 PAINTING RESULTS", "1 Mark ROTHKO (1903-1970) United States $99,000,000 1 0 $99,000,000",
        "TOP 500 ARTISTS BY AUCTION TURNOVER IN 2024",
        "1 Pablo PICASSO (1881-1973) Spain $500,000,000 10 1 $1",
        "2 Andy WARHOL (1928-1987) United States $400,000,000 10 1 $1",
        "3 Claude MONET (1840-1926) France $900,000,000 10 1 $1",           # misread: breaks the order
        "4 Joan MITCHELL (1925-1992) United States $100,000,000 10 1 $1",
    ])
    assert [r.rank for r in table(text)] == [1, 2, 4]


def test_names_match_in_either_order_and_any_case_with_their_birth_year():
    assert key("PiCaSSO Pablo", 1881) == key("Pablo PICASSO", 1881)
    assert key("sAInt-PHALLe de niki", 1930) == key("Niki de Saint-Phalle", 1930)
    assert key("Pablo PICASSO", 1881) != key("Pablo PICASSO", 1950)


def test_a_tables_first_page_before_the_repeated_heading_is_kept():
    text = "\n".join([
        "TOP 500 ARTISTS BY AUCTION TURNOVER IN 2024",                      # the contents page
        "TOP 100 WORKS", "1 Rene MAGRITTE (1898-1967) Les Chasseurs $9,610,000 19 Nov 2024",
        "1 Rene MAGRITTE (1898-1967) Belgium $312,337,360 175 70 $121,160,000 X",   # the table's first page
        "2 Pablo PICASSO (1881-1973) Spain $223,195,610 3,585 1,097 $24,800,000",
        "TOP 500 ARTISTS BY AUCTION TURNOVER IN 2024",                      # repeated on its second page
        "3 Joan MITCHELL (1925-1992) United States $100,000,000 10 1 $1",
    ])
    assert [(r.rank, r.turnover) for r in table(text)] == [(1, 312_337_360), (2, 223_195_610), (3, 100_000_000)]
