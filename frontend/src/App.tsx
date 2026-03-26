import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { I18nextProvider } from "react-i18next";
import i18n from "./i18n";
import Navbar from "./components/feature/Navbar";
import { AuthProvider } from "./context/AuthContext";

function App() {
  return (
    <I18nextProvider i18n={i18n}>
      <AuthProvider>
        <BrowserRouter basename={__BASE_PATH__}>
          <Navbar />
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </I18nextProvider>
  );
}

export default App;
