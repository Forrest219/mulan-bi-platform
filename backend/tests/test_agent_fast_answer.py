from app.api.agent import _build_fast_answer


def test_build_fast_answer_dimension_enumeration_uses_value_list_wording():
    answer = _build_fast_answer(
        "类别 都有什么",
        ["类别"],
        [["家具"], ["办公用品"], ["技术"]],
        "订单+ (示例 - 超市)",
        {"fields": ["类别"], "rows": [["家具"], ["办公用品"], ["技术"]]},
    )

    assert answer == "「类别」共有 3 个取值：家具、办公用品、技术。"
    assert "前几名" not in answer
