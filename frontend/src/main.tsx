import { createRoot } from "react-dom/client";
import App from "./App";
import { language } from "./i18n";
import "./style.css";

document.documentElement.lang = language;
createRoot(document.getElementById("root")!).render(<App />);
