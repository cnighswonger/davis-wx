import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import { WeatherDataProvider, useWeatherData } from './context/WeatherDataContext';
import AppShell from './components/layout/AppShell';
import Dashboard from './pages/Dashboard';
import History from './pages/History';
import Forecast from './pages/Forecast';
import Astronomy from './pages/Astronomy';
import Settings from './pages/Settings';

function AppContent() {
  const { connected, currentConditions } = useWeatherData();
  const lastUpdate = currentConditions?.timestamp
    ? new Date(currentConditions.timestamp)
    : null;

  return (
    <AppShell connected={connected} lastUpdate={lastUpdate}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/history" element={<History />} />
        <Route path="/forecast" element={<Forecast />} />
        <Route path="/astronomy" element={<Astronomy />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </AppShell>
  );
}

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <WeatherDataProvider>
          <AppContent />
        </WeatherDataProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
