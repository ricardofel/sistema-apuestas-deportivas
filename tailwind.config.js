// El tema (colores, radios, sombras, fuente) vive en static/js/tema-tailwind.js,
// compartido con el CDN que usa base.html en desarrollo.
const tema = require("./static/js/tema-tailwind.js");

module.exports = {
  content: ["./app/web/templates/**/*.html"],
  theme: { extend: tema },
  plugins: [],
};
