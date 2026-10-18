import json
import os

# Lấy thư mục hiện tại của file data_reader.py (đang là thư mục scripts)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Trỏ đường dẫn ra thư mục gốc, đi vào thư mục data
DATA_DIR = os.path.join(BASE_DIR, "../data")


def read_json(file_name):
    """Đọc dữ liệu từ file JSON."""
    file_path = os.path.join(DATA_DIR, file_name)

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise ValueError(
                f"{file_name} phải chứa một danh sách JSON."
            )

        return data

    except FileNotFoundError:
        raise FileNotFoundError(
            f"Không tìm thấy file: {file_name}"
        )

    except json.JSONDecodeError as error:
        raise ValueError(
            f"File {file_name} không đúng định dạng JSON: {error}"
        )


def read_courses():
    """Đọc danh sách môn học."""
    return read_json("courses_detailed.json")


def read_students():
    """Đọc danh sách hồ sơ sinh viên."""
    return read_json("student_profile.json")


if __name__ == "__main__":
    try:
        courses = read_courses()
        students = read_students()

        print(f"Đọc thành công {len(courses)} môn học.")
        print(f"Đọc thành công {len(students)} hồ sơ sinh viên.")

        print("\nDanh sách môn học:")
        for course in courses:
            print(f"- {course['course_id']}: {course['course_name']}")

        print("\nDanh sách sinh viên:")
        for student in students:
            print(f"- {student['student_id']}: {student['full_name']}")

    except (FileNotFoundError, ValueError) as error:
        print(f"Lỗi: {error}")
