from data_reader import read_courses, read_students


def validate_courses(courses):
    errors = []
    warnings = []

    course_ids = set()
    section_ids = set()

    # Kiểm tra từng môn học
    for index, course in enumerate(courses):
        if not isinstance(course, dict):
            errors.append(f"courses[{index}] không phải object.")
            continue

        course_id = course.get("course_id")
        course_name = course.get("course_name")
        credits = course.get("credits")
        prerequisites = course.get("prerequisites")
        sections = course.get("sections")

        # Kiểm tra trường bắt buộc
        if not isinstance(course_id, str) or not course_id.strip():
            errors.append(f"courses[{index}] thiếu course_id.")
        elif course_id in course_ids:
            errors.append(f"Trùng mã môn: {course_id}.")
        else:
            course_ids.add(course_id)

        if not isinstance(course_name, str) or not course_name.strip():
            errors.append(f"Môn {course_id} thiếu course_name.")

        if (
            not isinstance(credits, int)
            or isinstance(credits, bool)
            or credits <= 0
        ):
            errors.append(f"Môn {course_id} có credits không hợp lệ.")

        if not isinstance(prerequisites, str):
            errors.append(
                f"Môn {course_id} có prerequisites không hợp lệ."
            )

        if not isinstance(sections, list):
            errors.append(f"Môn {course_id} thiếu danh sách sections.")
            continue

        # Kiểm tra lớp học phần
        for section in sections:
            if not isinstance(section, dict):
                errors.append(
                    f"Môn {course_id} có section không hợp lệ."
                )
                continue

            section_id = section.get("section_id")

            if not isinstance(section_id, str) or not section_id.strip():
                errors.append(
                    f"Môn {course_id} có section thiếu section_id."
                )
            elif section_id in section_ids:
                errors.append(f"Trùng mã lớp học phần: {section_id}.")
            else:
                section_ids.add(section_id)

            for field in (
                "semester", "class", "timetable", "lab_timetable"
            ):
                if field not in section:
                    errors.append(
                        f"Lớp {section_id} thiếu trường {field}."
                    )

            if not section.get("timetable") and not section.get(
                "lab_timetable"
            ):
                warnings.append(
                    f"Lớp {section_id} chưa có lịch học."
                )

    # Kiểm tra môn tiên quyết có tồn tại không
    for course in courses:
        if not isinstance(course, dict):
            continue

        course_id = course.get("course_id")
        prerequisites = course.get("prerequisites")

        if not isinstance(prerequisites, str) or not prerequisites.strip():
            continue

        # Hỗ trợ một hoặc nhiều mã môn, ngăn cách bằng dấu phẩy
        prerequisite_ids = [
            item.strip() for item in prerequisites.split(",")
            if item.strip()
        ]

        for prerequisite_id in prerequisite_ids:
            if prerequisite_id not in course_ids:
                errors.append(
                    f"Môn {course_id} có môn tiên quyết "
                    f"không tồn tại: {prerequisite_id}."
                )

            if prerequisite_id == course_id:
                errors.append(
                    f"Môn {course_id} không thể là tiên quyết của chính nó."
                )

    return errors, warnings


def validate_students(students, course_ids):
    errors = []
    warnings = []
    student_ids = set()

    for index, student in enumerate(students):
        if not isinstance(student, dict):
            errors.append(f"students[{index}] không phải object.")
            continue

        student_id = student.get("student_id")
        full_name = student.get("full_name")
        credits = student.get("accumulated_credits")
        gpa = student.get("gpa")
        completed_courses = student.get("completed_courses")

        if not isinstance(student_id, str) or not student_id.strip():
            errors.append(f"students[{index}] thiếu student_id.")
        elif student_id in student_ids:
            errors.append(f"Trùng mã sinh viên: {student_id}.")
        else:
            student_ids.add(student_id)

        if not isinstance(full_name, str) or not full_name.strip():
            errors.append(f"Sinh viên {student_id} thiếu full_name.")

        if (
            not isinstance(credits, int)
            or isinstance(credits, bool)
            or credits < 0
        ):
            errors.append(
                f"Sinh viên {student_id} có accumulated_credits "
                "không hợp lệ."
            )

        if (
            not isinstance(gpa, (int, float))
            or isinstance(gpa, bool)
            or not 0 <= gpa <= 4
        ):
            errors.append(f"Sinh viên {student_id} có GPA không hợp lệ.")

        if not isinstance(completed_courses, list):
            errors.append(
                f"Sinh viên {student_id} có completed_courses "
                "không hợp lệ."
            )
            continue

        if len(completed_courses) != len(set(
            item for item in completed_courses if isinstance(item, str)
        )):
            warnings.append(
                f"Sinh viên {student_id} có mã môn hoàn thành bị lặp."
            )

        for course_id in completed_courses:
            if not isinstance(course_id, str):
                errors.append(
                    f"Sinh viên {student_id} có mã môn sai kiểu dữ liệu."
                )
            elif course_id not in course_ids:
                errors.append(
                    f"Sinh viên {student_id} tham chiếu môn "
                    f"không tồn tại: {course_id}."
                )

    return errors, warnings


def main():
    try:
        courses = read_courses()
        students = read_students()
    except (OSError, ValueError) as error:
        print(f"Không thể đọc dữ liệu: {error}")
        return

    course_errors, course_warnings = validate_courses(courses)

    course_ids = {
        course["course_id"]
        for course in courses
        if isinstance(course, dict)
        and isinstance(course.get("course_id"), str)
    }

    student_errors, student_warnings = validate_students(
        students, course_ids
    )

    errors = course_errors + student_errors
    warnings = course_warnings + student_warnings

    print("===== DATA VALIDATION REPORT =====")
    print(f"Tổng số môn học: {len(courses)}")
    print(f"Tổng số hồ sơ sinh viên: {len(students)}")
    print(f"Số lỗi: {len(errors)}")
    print(f"Số cảnh báo: {len(warnings)}")

    if errors:
        print("\n--- ERRORS ---")
        for error in errors:
            print(f"[ERROR] {error}")

    if warnings:
        print("\n--- WARNINGS ---")
        for warning in warnings:
            print(f"[WARNING] {warning}")

    if not errors and not warnings:
        print("\nDữ liệu hợp lệ, không có cảnh báo.")

    elif not errors:
        print("\nKhông có lỗi nghiêm trọng, nhưng cần xem cảnh báo.")


if __name__ == "__main__":
    main()
