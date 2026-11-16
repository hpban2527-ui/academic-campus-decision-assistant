# Từ Điển Ký Hiệu Toán Học & Thuật Ngữ Giải Thuật SP3 (Beginner-Friendly Glossary)

> [!NOTE]
> Tài liệu này đi kèm với [Báo cáo Kỹ thuật SP3](./SP3_SCHEDULE_OPTIMIZATION_REPORT.md), được viết dành riêng cho người mới bắt đầu. Mọi ký hiệu toán học xuất hiện trong báo cáo đều được dịch sang **ngôn ngữ đời thường**, kèm **cách đọc bằng lời** và **ví dụ thực tế trong bài toán tính điểm rèn luyện (DRL)**.

---

## Phần 1: Các Ký Hiệu Toán Học Cơ Bản (Đọc Công Thức Như Đọc Tiếng Việt)

Nếu bạn nhìn thấy các ký hiệu lạ như $\in, \subseteq, \forall, \sum, \mathbb{I}[\dots]$, bảng dưới đây sẽ giúp bạn "dịch" chúng sang tiếng Việt hoặc code Python tương đương ngay lập tức:

| Ký hiệu | Cách đọc bằng lời | Ý nghĩa tự nhiên (Đời thường) | Tương đương trong Python | Ví dụ trong bài toán xếp lịch |
| :---: | :--- | :--- | :--- | :--- |
| $\{x_1, x_2\}$ | Tập hợp (Set) | Một cái giỏ chứa các phần tử không trùng nhau. | `set([x1, x2])` | $S = \{\text{Hội thảo AI}, \text{Hiến máu}\}$ là một lịch gồm 2 hoạt động. |
| $\in$ | "Thuộc" / "Nằm trong" | Phần tử này nằm bên trong danh sách/tập hợp kia. | `x in S` | $a_i \in \mathcal{C}$ nghĩa là: "Hoạt động $a_i$ nằm trong danh sách ứng viên $\mathcal{C}$". |
| $\notin$ | "Không thuộc" | Phần tử này **không** nằm trong danh sách kia. | `x not in S` | $\{u, v\} \notin E$ nghĩa là: "Cặp hoạt động $u$ và $v$ không nằm trong danh sách bị trùng giờ $E$". |
| $\subseteq$ | "Là tập con của" | Mọi phần tử của nhóm nhỏ đều nằm trong nhóm lớn. | `K.issubset(S)` | $K \subseteq S$ nghĩa là: "Tất cả các hoạt động sinh viên yêu cầu giữ lại ($K$) đều phải có mặt trong lịch đề xuất ($S$)". |
| $\lvert S \rvert$ | "Số phần tử của $S$" | Đếm xem trong giỏ $S$ có bao nhiêu món. | `len(S)` | Nếu lịch $S$ có 3 hoạt động thì $\lvert S \rvert = 3$. |
| $\varnothing$ | "Tập rỗng" | Danh sách trống trơn, không có phần tử nào (số lượng $= 0$). | `set()` hoặc `[]` | $K = \varnothing$ nghĩa là sinh viên không yêu cầu giữ cố định hoạt động nào. |
| $A \cup B$ | "Hợp của $A$ và $B$" | Gom tất cả phần tử của cả $A$ và $B$ lại (bỏ trùng). | `A \| B` | $S \cup \{a_i\}$ nghĩa là: "Lấy lịch hiện tại $S$ rồi nhét thêm hoạt động $a_i$ vào". |
| $A \cap B$ | "Giao của $A$ và $B$" | Chỉ lấy những phần tử **xuất hiện ở cả 2 bên** $A$ và $B$. | `A & B` | $S \cap S'$ là các hoạt động bị trùng nhau giữa 2 phương án lịch $S$ và $S'$. |
| $A \setminus B$ | "Hiệu của $A$ và $B$" | Có trong $A$ nhưng **bỏ đi** những gì có trong $B$. | `A - B` | $S \setminus \{a\}$ nghĩa là: "Thử xóa bớt hoạt động $a$ ra khỏi lịch $S$". |
| $\forall$ | "Với mọi" | Bắt buộc đúng với tất cả từng phần tử một, không sót cái nào. | `all(...)` / vòng lặp `for` | $\forall u, v \in S$ nghĩa là: "Cứ lấy bất kỳ 2 hoạt động $u, v$ nào trong lịch $S$ ra kiểm tra...". |
| $\land$ | "Và" (Logic AND) | Cả hai vế trái và phải đều phải đúng cùng lúc. | `and` | $(G_{\text{cat}} = 0) \land (G_{\text{tot}} = 0)$ nghĩa là: "Đủ điểm từng mục **VÀ** đủ cả tổng điểm". |
| $\iff$ | "Khi và chỉ khi" | Hai vế tương đương hoàn toàn với nhau. | `==` (kiểu `bool`) | Đạt mục tiêu (`meets_targets`) **khi và chỉ khi** không còn thiếu điểm nào. |
| $\sum$ | "Tổng Sigma" | Cộng dồn giá trị của tất cả các phần tử lại. | `sum(...)` | $\sum_{a_i \in S} d_i$ nghĩa là: "Cộng thời lượng $d_i$ của từng hoạt động trong lịch $S$ lại để ra tổng số phút". |
| $\mathbb{I}[\text{điều kiện}]$ | "Hàm chỉ thị" (Indicator) | Nếu điều kiện bên trong ngoặc **Đúng thì bằng $1$**, nếu **Sai thì bằng $0$**. | `1 if cond else 0` | $\mathbb{I}[\text{mode}(a_i) \in \mathcal{P}_{\text{mode}}]$: Nếu hoạt động đúng hình thức sinh viên thích (ví dụ `online`) thì được $+1$ điểm thưởng, ngược lại được $0$. |
| $\arg\min_{S} f(S)$ | "Phần tử làm hàm nhỏ nhất" | Thay vì lấy giá trị nhỏ nhất, hãy **trả về chính phương án $S$** đạt giá trị nhỏ nhất đó. | `min(pool, key=f)` | $S^* = \arg\min_{S} \mathbf{r}(S)$ là: "Tìm ra phương án lịch $S^*$ có thứ hạng tốt nhất". |
| $\binom{N}{k}$ | "Tổ hợp chập $k$ của $N$" | Số cách chọn ra $k$ hoạt động từ danh sách $N$ hoạt động. | `math.comb(N, k)` | Có $N=100$ hoạt động, muốn chọn thử $k=2$ hoạt động thì có $\binom{100}{2} = 4,950$ cặp khác nhau. |
| $O(\dots)$ | "Độ phức tạp Big-O" | Ước lượng số bước máy tính phải chạy khi dữ liệu đầu vào lớn lên. | — | $O(1)$ là chạy tức thì (1 bước); $O(N)$ là duyệt 1 vòng; $O(2^k)$ là tăng gấp đôi mỗi khi thêm 1 phần tử (rất chậm). |

---

## Phần 2: Ý Nghĩa Thực Tế Của Từng Biến Số Trong Báo Cáo

### 2.1. Nhóm biến đầu vào (Dữ liệu hoạt động & Ràng buộc của sinh viên)

| Ký hiệu trong báo cáo | Tên biến trong code Python | Giải thích bằng ngôn ngữ tự nhiên & Ví dụ thực tế |
| :---: | :--- | :--- |
| $\mathcal{C}$ | `candidates` | **Danh sách toàn bộ hoạt động ứng viên** có thể chọn (ví dụ 200 hoạt động của trường trong học kỳ). |
| $N$ | `len(candidates)` | **Tổng số lượng hoạt động ứng viên** đầu vào (ví dụ $N = 100, 250, 500$). |
| $a_i$ | `candidate` | **Hoạt động thứ $i$** trong danh sách (ví dụ $a_1 =$ *"Hội thảo Trí tuệ nhân tạo"*). |
| $d_i$ | `candidate.minutes` | **Thời lượng (số phút)** phải bỏ ra để tham gia hoạt động $a_i$ (ví dụ $d_1 = 90$ phút). |
| $\mathcal{A}$ | `available_intervals` | **Các khoảng thời gian rảnh trong tuần** của sinh viên (sau khi đã trừ lịch học trên trường và lịch bận cá nhân). |
| $K$ | `plan.kept` (`keep_requests`) | **Các hoạt động sinh viên bấm nút "Giữ cố định"**: Bắt buộc phải xuất hiện trong lịch mới và không được đổi giờ. |
| $P$ | `plan.retained` | **Các hoạt động trong lịch cũ** mà sinh viên chưa hoàn thành (dùng để so sánh xem lịch mới thay đổi nhiều hay ít so với lịch cũ). |
| $E$ | `plan.conflicts` (`conflict_pairs`) | **Danh sách các cặp hoạt động bị đụng giờ nhau**: Nếu cặp $\{a_1, a_2\} \in E$ thì không bao giờ được chọn cả $a_1$ lẫn $a_2$ cùng lúc. |
| $M_{\max}$ | `limits.max_activities` | **Số hoạt động tối đa** sinh viên muốn tham gia (ví dụ: *"Tôi chỉ muốn đi tối đa 5 hoạt động"* $\implies M_{\max} = 5$). |
| $T_{\max}$ | `limits.max_duration_minutes` | **Tổng số phút tối đa** sinh viên chịu bỏ ra (ví dụ: *"Tối đa 360 phút = 6 tiếng"* $\implies T_{\max} = 360$). |
| $\varepsilon$ | `ABS_TOLERANCE = 1e-9` | **Sai số số thực cực nhỏ** ($0.000000001$) để tránh lỗi làm tròn dấu phẩy động của máy tính khi so sánh bằng. |
| $[r_i, \text{dl}_i]$ | `usable_window` | Với hoạt động giờ giấc linh hoạt (`FLEXIBLE_WINDOW`, ví dụ làm Quiz online): $r_i$ là **giờ mở cổng** (Release time), $\text{dl}_i$ là **hạn chót đóng cổng** (Deadline). |

---

### 2.2. Nhóm biến Điểm rèn luyện (DRL) & Mục tiêu (Goals)

| Ký hiệu trong báo cáo | Tên biến trong code Python | Giải thích bằng ngôn ngữ tự nhiên & Ví dụ thực tế |
| :---: | :--- | :--- |
| $S$ | `activity_ids` / `subset` | **Một phương án lịch đang xét** (một nhóm các hoạt động được chọn thử để chấm điểm). |
| $c \in \mathcal{M}$ | `category` (`C1`..`C5`) | **Mục điểm rèn luyện** trong quy chế trường (ví dụ `C1`: Học tập, `C3`: Chính trị - Xã hội, `C4`: Tình nguyện...). |
| $\text{Cap}_c$ | `category_caps[c]` | **Điểm trần tối đa của mục $c$**. Ví dụ mục `C1` có trần $\text{Cap}_{C1} = 30$ điểm — dù bạn tham gia thêm bao nhiêu hội thảo học thuật nữa thì mục `C1` cũng không vượt quá 30 được. |
| $A_c(S)$ | `result["category_after"][c]` | **Điểm dự kiến của mục $c$ sau khi tham gia lịch $S$** (do hệ thống SP2 tính ra). |
| $A_{\text{tot}}(S)$ | `result["total_after"]` | **Tổng điểm rèn luyện toàn học kỳ dự kiến** sau khi tham gia lịch $S$ (tối đa 100 điểm). |
| $T_c$ | `category_targets[c]` | **Điểm mục tiêu sinh viên muốn đạt ở mục $c$** (ví dụ: muốn mục `C1` đạt ít nhất $T_{C1} = 25$ điểm). |
| $T_{\text{tot}}$ | `total_target` | **Tổng điểm rèn luyện mục tiêu** sinh viên muốn đạt (ví dụ: muốn đạt loại Xuất sắc $T_{\text{tot}} = 90$ điểm). |
| $G_{\text{cat}}(S)$ | `category_gap` | **Tổng số điểm còn thiếu ở các mục** so với mục tiêu. Nếu mục `C1` cần 25 mà mới được 22, mục `C3` cần 20 mà đã được 25 (dư 5, tính thiếu $= 0$), thì $G_{\text{cat}}(S) = (25 - 22) + 0 = 3$ điểm. Khi $G_{\text{cat}}(S) = 0$ tức là **mọi mục đều đã đạt chỉ tiêu**. |
| $G_{\text{tot}}(S)$ | `total_gap` | **Số điểm tổng còn thiếu** so với mục tiêu tổng $T_{\text{tot}}$. Nếu cần 80 điểm mà lịch $S$ giúp đạt 85 điểm thì $G_{\text{tot}}(S) = 0$ (không thiếu). |
| $\Delta_{\text{set}}(S)$ | `set_changes` | **Số hoạt động bị xáo trộn (thêm mới hoặc bỏ đi)** khi cập nhật lại lịch cũ. Càng nhỏ thì lịch mới càng giống lịch cũ. |
| $\Delta_{\text{time}}(S)$ | `time_changes` | **Số hoạt động cũ bị dời sang khung giờ khác** khi xếp lại lịch. |
| $D(S)$ | `duration` | **Tổng thời gian (phút) của cả lịch $S$** (cộng thời lượng tất cả hoạt động trong $S$ lại). |
| $P(S)$ và $\bar{P}(S)$ | `preference` và `avg_pref` | $P(S)$ là **tổng điểm thưởng khớp sở thích** (đúng lĩnh vực thích, đúng hình thức online/offline, đúng cơ sở 1/cơ sở 2, đúng khung giờ sáng/chiều). $\bar{P}(S) = P(S) / \lvert S \rvert$ là **điểm khớp sở thích trung bình trên mỗi hoạt động**. |

---

## Phần 3: Giải Nghĩa Từng Công Thức "Khó Nhằn" Nhất Trong Báo Cáo

Dưới đây là 4 công thức quan trọng nhất trong báo cáo được "mổ xẻ" từng chữ một bằng ví dụ số học cụ thể:

### 1. Thứ tự từ điển (Lexicographic Tuple Ranking): $\mathbf{r}(S_1) <_{\text{lex}} \mathbf{r}(S_2)$
- **Tại sao gọi là "thứ tự từ điển"?**
  Giống hệt cách bạn tra từ điển tiếng Anh hoặc cách Python so sánh 2 `tuple`: Máy tính so sánh **thành phần thứ 1** trước; nếu bằng nhau mới xét đến **thành phần thứ 2**; nếu vẫn bằng nhau mới xét đến **thành phần thứ 3**...
- **Tại sao một số biến có dấu trừ đằng trước (như $-P(S)$ hoặc $-A_{\text{tot}}(S)$)?**
  Vì quy ước của hàm sắp xếp trong Python (`min` / `sort`) là **số nhỏ hơn đứng trước (tốt hơn)**:
  - Với **Độ thiếu điểm ($G_{\text{cat}}, G_{\text{tot}}$)**, **Số hoạt động ($\lvert S \rvert$)**, **Thời gian ($D(S)$)**: Càng **nhỏ** càng tốt $\implies$ giữ nguyên dấu dương.
  - Với **Tổng điểm đạt được ($A_{\text{tot}}$)** hay **Độ khớp sở thích ($P(S)$)**: Càng **lớn** càng tốt $\implies$ thêm **dấu trừ (`-`)** ở trước (ví dụ đạt 80 điểm thành `-80`, đạt 70 điểm thành `-70`; vì `-80 < -70` nên phương án 80 điểm được xếp hạng cao hơn!).

---

### 2. Công thức Độ tăng điểm thực tế có xét trần (Cap-Aware Effective Gain — Mục 4, Pha 2)
Trong báo cáo có công thức:
$$\tilde{\Delta}_c(a_i \mid S) = \min\Bigl(\Delta_c(a_i), \; \max\bigl(0, \, \text{Cap}_c - A_c(S)\bigr)\Bigr)$$

- **Cách đọc ký hiệu $\tilde{\Delta}_c(a_i \mid S)$**: *"Số điểm thực tế mà hoạt động $a_i$ cộng thêm được vào mục $c$, biết rằng sinh viên đã chọn sẵn lịch $S$"* (dấu gạch đứng $\mid$ đọc là *"biết rằng"* hoặc *"tại trạng thái"*).
- **Ví dụ thực tế cực dễ hiểu**:
  - Giả sử mục `C1` có trần tối đa là $\text{Cap}_{C1} = 30$ điểm.
  - Lịch hiện tại $S$ của bạn đã giúp mục `C1` đạt $A_{C1}(S) = 27$ điểm $\implies$ Khoảng trống còn lại dưới trần chỉ là:
    $$\text{Cap}_{C1} - A_{C1}(S) = 30 - 27 = 3 \text{ điểm}$$
  - Bây giờ bạn định chọn thêm hoạt động $a_i$ (*"Cuộc thi Học thuật"*), vốn dĩ có điểm gốc là $\Delta_{C1}(a_i) = 10$ điểm.
  - Nhưng vì mục `C1` chỉ còn trống $3$ điểm nữa là kịch trần, nên **điểm thực tế tăng thêm** chỉ là:
    $$\tilde{\Delta}_{C1}(a_i \mid S) = \min(10, \, 3) = 3 \text{ điểm (chứ không phải 10 điểm!)}$$
  - Thậm chí nếu $A_{C1}(S) = 30$ (đã kịch trần, còn trống $0$ điểm), thì $\tilde{\Delta}_{C1}(a_i \mid S) = \min(10, 0) = 0$. Thuật toán biết ngay việc thêm $a_i$ là **vô ích (0 điểm)** nên bỏ qua ngay mà không cần gọi SP2 chấm điểm!

---

### 3. Khái niệm "Hàm Cận Mô-đun" (Submodular Function — Mục 1.2 & Pha 3)
- **Nghe tên rất toán học, nhưng thực chất là quy luật gì?**
  Trong kinh tế và đời sống, đó chính là **"Quy luật hiệu suất giảm dần" (Diminishing Returns)**:
  > Cùng một hoạt động $a_i$, nếu thêm nó vào lúc bảng điểm của bạn đang **trống** thì nó cộng được **nhiều điểm** (ví dụ $+10$ điểm); nhưng nếu thêm nó vào lúc bảng điểm của bạn đã **gần đầy (sắp chạm trần mục hoặc chạm trần 100 điểm)** thì số điểm nó cộng thêm được sẽ **ít đi hoặc bằng 0**.
- **Ứng dụng để cắt tỉa (Submodular Zero-Gain Pruning)**:
  Nhờ tính chất này, nếu ở bước hiện tại việc thêm hoạt động $a_i$ vào lịch $S$ đã cho **0 điểm tăng thêm**, thì ở mọi bước về sau (khi lịch $S$ còn phình to hơn nữa), hoạt động $a_i$ đó chắc chắn cũng chỉ cho **0 điểm tăng thêm**. Do đó ta thẳng tay cắt bỏ nhánh đó!

---

### 4. Công thức Khoảng cách Jaccard để tạo nhiều lịch đa dạng (`_jaccard_distance` — Mục 5.2)
Trong báo cáo có công thức:
$$d_J(S, S') = 1 - \frac{\lvert S \cap S' \rvert}{\lvert S \cup S' \rvert} \ge \tau$$

- **Mục đích**: Khi đề xuất 5 phương án lịch cho sinh viên chọn, ta không muốn phương án 2 giống tới 90% phương án 1. Khoảng cách Jaccard $d_J(S, S')$ đo **tỷ lệ khác biệt** giữa hai phương án lịch $S$ và $S'$ (giá trị từ $0$ đến $1$):
  - Nếu $S$ và $S'$ **giống hệt nhau**: $d_J = 0$ ($0\%$ khác biệt).
  - Nếu $S$ và $S'$ **không trùng bất kỳ hoạt động nào**: $d_J = 1$ ($100\%$ khác biệt).
- **Ví dụ tính nhẩm**:
  - Phương án 1: $S = \{A, B, C\}$.
  - Phương án 2: $S' = \{A, B, D\}$.
  - Số hoạt động trùng nhau: $\lvert S \cap S' \rvert = \lvert \{A, B\} \rvert = 2$.
  - Tổng số hoạt động của cả hai gộp lại: $\lvert S \cup S' \rvert = \lvert \{A, B, C, D\} \rvert = 4$.
  - Khoảng cách Jaccard:
    $$d_J(S, S') = 1 - \frac{2}{4} = 0.5 \quad (50\% \text{ khác biệt})$$
  - Vì $0.5 \ge \tau$ (với ngưỡng $\tau = 0.25$), Phương án 2 đủ độ mới mẻ so với Phương án 1 nên được giữ lại để đề xuất cho người dùng!
