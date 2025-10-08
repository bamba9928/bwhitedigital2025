document.addEventListener("DOMContentLoaded", function () {
    const roleField = document.querySelector("#id_role");
    const gradeRow = document.querySelector(".form-row.field-grade");

    if (!roleField || !gradeRow) return;

    function toggleGrade() {
        if (roleField.value === "APPORTEUR") {
            gradeRow.style.display = "";  // Afficher
        } else {
            gradeRow.style.display = "none";  // Masquer
            const gradeSelect = gradeRow.querySelector("select");
            if (gradeSelect) gradeSelect.value = ""; // reset si ADMIN
        }
    }

    // Initialisation
    toggleGrade();

    // Sur changement de rôle
    roleField.addEventListener("change", toggleGrade);
});
