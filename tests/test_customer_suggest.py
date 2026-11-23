"""The customers offered while a name is typed in Phiếu xuất kho (user's request 24/11/2026)."""

from dibekho.core.issues import suggest_customers

LABELS = [
    "Công ty A · 0900 000 001",
    "Khách Mẫu · 0900 000 002",
    "Đại lý Chưa Mua",
    "Cửa hàng Khánh · 0911 222 333",
]


def names(typed):
    return [LABELS[i] for i in suggest_customers(LABELS, typed)]


def test_nothing_typed_offers_everyone():
    assert names("") == LABELS
    assert names("   ") == LABELS


def test_without_accents():
    assert names("khach mau") == ["Khách Mẫu · 0900 000 002"]
    assert names("KHACH") == ["Khách Mẫu · 0900 000 002"]  # 'Khánh' is khanh, not khach
    assert names("kh") == ["Khách Mẫu · 0900 000 002", "Cửa hàng Khánh · 0911 222 333"]


def test_with_accents_too():
    assert names("Khánh") == ["Cửa hàng Khánh · 0911 222 333"]


def test_dd_is_d():
    assert names("dai ly") == ["Đại lý Chưa Mua"]


def test_words_in_any_order():
    assert names("mau khach") == ["Khách Mẫu · 0900 000 002"]


def test_part_of_a_phone_number():
    assert names("0911") == ["Cửa hàng Khánh · 0911 222 333"]
    assert names("000 001") == ["Công ty A · 0900 000 001"]


def test_nothing_fits():
    assert names("xyz") == []
