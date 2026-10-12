/*
  Tema de Tailwind del portal: única fuente de verdad.
  - En desarrollo lo carga base.html después del CDN de Tailwind (window.tailwind.config).
  - En la compilación de producción lo lee tailwind.config.js (require).
  Los valores son variables CSS definidas en static/css/portal.css.
*/
(function (raiz) {
  var escala = function (nombre, pasos) {
    var colores = {};
    pasos.forEach(function (paso) {
      colores[paso] = "var(--" + nombre + "-" + paso + ")";
    });
    return colores;
  };

  var tema = {
    fontFamily: { sans: ["Archivo", "system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
    colors: {
      slate: escala("slate", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
      emerald: escala("emerald", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
      rose: escala("rose", [50, 100, 200, 600, 700, 800]),
      amber: escala("amber", [50, 100, 200, 800]),
    },
    borderRadius: { lg: "3px", xl: "4px", full: "3px" },
    boxShadow: { sm: "none", md: "none", lg: "none", xl: "none" },
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = tema;
  } else {
    raiz.tailwind.config = { theme: { extend: tema } };
  }
})(typeof window !== "undefined" ? window : globalThis);
