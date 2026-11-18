from sp1.features import topics


def activity(title: str, domain: str = "academic") -> dict:
    return {"title": title, "domain": domain}


def test_subject_topics_cover_the_common_academic_vocabulary():
    assert topics(activity("Hội thảo Vật lý lượng tử"), None)[:2] == ["physics", "research"]
    assert topics(activity("AI trong Hóa học"), None)[:2] == ["chemistry", "artificial_intelligence"]
    assert topics(activity("Phân tích hình ảnh trong nghiên cứu Sinh học"), None)[:2] == ["biology", "research"]
    assert topics(activity("Workshop học Tiếng Anh"), None)[:2] == ["foreign_language", "research"]


def test_math_and_physics_can_coexist_on_one_activity():
    assert topics(activity("Seminar Toán học và Vật lý"), None)[:2] == ["mathematics", "physics"]
