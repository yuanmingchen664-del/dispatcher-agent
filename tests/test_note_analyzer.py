from backend.app.services.note_analyzer import analyze_note_message


def test_analyze_note_message_with_prefix_and_scenario():
    note = analyze_note_message(
        "记一下 关于低能见度放行：目的地 RVR 波动较大时，先看趋势报和备降机场天气。"
    )

    assert note is not None
    assert note.scenario == "低能见度放行"
    assert note.title == "低能见度放行经验记录"
    assert "RVR" in note.content


def test_analyze_note_message_infers_scenario():
    note = analyze_note_message("帮我记住 起飞备降机场距离限制要结合发动机数量判断。")

    assert note is not None
    assert note.scenario == "起飞备降"
    assert note.source_type == "experience"
    assert note.reliability == "experiential"


def test_analyze_note_message_ignores_normal_question():
    assert analyze_note_message("CCAR121 部 U 章有什么要求？") is None
