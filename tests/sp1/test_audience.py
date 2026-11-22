from sp1.audience import (BASIS_FIT, BASIS_FREE_TEXT, BASIS_OPEN, BASIS_UNCLEAR, classify)


def basis(*lines):
    return classify("\n".join(lines), None)["basis"]


def test_all_students_with_lecturers_of_one_faculty_is_open():
    # Regression: the faculty belongs to the lecturers invited, not to the students.
    assert basis("Sinh viên toàn Trường và giảng viên Khoa Công nghệ thông tin") == BASIS_OPEN
    assert basis("Toàn thể sinh viên, cán bộ và giảng viên khoa Hóa học") == BASIS_OPEN


def test_a_faculty_named_for_students_is_still_a_restriction():
    assert basis("Sinh viên Khoa Hóa học") == BASIS_FREE_TEXT
    assert basis("Toàn thể giảng viên và sinh viên khoa Toán - Tin học") == BASIS_FREE_TEXT
    assert basis("Sinh viên khoa Công nghệ thông tin") == BASIS_FIT
    # Without an explicit all-students marker the faculty stays a restriction (never silently open).
    assert basis("Giảng viên Khoa Công nghệ thông tin") == BASIS_FIT
    # "Toàn thể" applies to the lecturers here, not to students: still restricted, never open.
    assert basis("Toàn thể giảng viên Khoa Công nghệ thông tin") == BASIS_FIT


def test_related_fields_are_not_a_named_programme():
    # Regression: "chuyên ngành liên quan" matched the programme rule through the word "liên".
    assert basis("Giảng viên, nghiên cứu sinh, học viên cao học và sinh viên các chuyên ngành liên quan, "
                 "các nhà khoa học quan tâm đến lĩnh vực Sinh học không gian.") == BASIS_OPEN
    assert basis("Sinh viên ngành Quản lý tài nguyên và môi trường và các ngành có liên quan") == BASIS_FREE_TEXT


def test_becoming_a_teacher_is_a_topic_not_an_audience():
    # Regression: "trở thành giáo viên" matched the teacher restriction.
    assert basis('Nếu bạn đang quan tâm đến "nghề giáo" hoặc muốn hiểu rõ hơn về con đường trở thành giáo viên '
                 "Toán tại các trường công lập") == BASIS_OPEN
    assert basis("Dành cho giáo viên Toán đang giảng dạy") == BASIS_FREE_TEXT
    assert basis("toàn thể chiến sĩ tình nguyện Mùa hè Xanh 2026") == BASIS_FREE_TEXT
