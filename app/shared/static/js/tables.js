window.initTeacherClassTable = function initTeacherClassTable() {
  const table = document.querySelector(".teacher-sortable-table");
  if (!table) {
    return;
  }

  const classId = table.dataset.classId;
  if (!classId) {
    return;
  }

  const rows = table.querySelectorAll("tbody tr.teacher-clickable-row");
  rows.forEach(function (row) {
    row.addEventListener("click", async function () {
      const studentId = row.dataset.studentId;
      if (!studentId) {
        return;
      }

      const detailRow = document.getElementById("student-punches-" + studentId);
      if (!detailRow) {
        return;
      }

      if (!detailRow.hidden) {
        detailRow.hidden = true;
        return;
      }

      detailRow.hidden = false;
      const container = detailRow.querySelector(".teacher-punch-detail-content");
      if (!container || container.dataset.loaded === "true") {
        return;
      }

      container.textContent = "Loading...";

      try {
        const response = await fetch(`/teacher/classes/${classId}/students/${studentId}/punches`);
        if (!response.ok) {
          throw new Error("Failed to load punches");
        }
        const html = await response.text();
        container.innerHTML = html;
        container.dataset.loaded = "true";
      } catch {
        container.textContent = "Unable to load punch history.";
      }
    });
  });
};
