import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import { useDemoStore } from './demo/demoState'
import Login from './pages/auth/Login'
import Dashboard from './pages/dashboard/Dashboard'

import MarketEnvironmentsList from './pages/market/MarketEnvironmentsList'
import CreateMarketEnvironment from './pages/market/CreateMarketEnvironment'
import MarketData from './pages/market/MarketData'
import Instruments from './pages/market/Instruments'
import Replay from './pages/market/Replay'

import SimulationsList from './pages/simulation/SimulationsList'
import ConfigureSimulation from './pages/simulation/ConfigureSimulation'
import RunSimulation from './pages/simulation/RunSimulation'
import SimulationResults from './pages/simulation/SimulationResults'
import Calibrations from './pages/simulation/Calibrations'
import Models from './pages/simulation/Models'

import Strategies from './pages/trading/Strategies'
import ConfigureStrategy from './pages/trading/ConfigureStrategy'
import Portfolios from './pages/trading/Portfolios'
import CreatePortfolio from './pages/trading/CreatePortfolio'
import TradeReplay from './pages/trading/TradeReplay'

import RiskOverview from './pages/risk/RiskOverview'
import StressTesting from './pages/risk/StressTesting'
import TdaAnalysis from './pages/tda/TdaAnalysis'
import Explanations from './pages/explainability/Explanations'
import CompositeRiskPage from './pages/risk/CompositeRiskPage'
import Attribution from './pages/risk/Attribution'

import MLModelsPage from './pages/ml/MLModelsPage'
import Predictions from './pages/ml/Predictions'
import Features from './pages/ml/Features'

import AlertsPage from './pages/alerts/AlertsPage'
import Reports from './pages/other/Reports'
import AuditLog from './pages/other/AuditLog'
import Settings from './pages/other/Settings'
import Architecture from './pages/other/Architecture'

import Users from './pages/administration/Users'
import Roles from './pages/administration/Roles'
import System from './pages/administration/System'
import NotFound from './pages/other/NotFound'

function RequireAuth({ children }: { children: React.ReactElement }) {
  const authenticated = useDemoStore((s) => s.authenticated)
  if (!authenticated) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />

        <Route path="/market/environments" element={<MarketEnvironmentsList />} />
        <Route path="/market/environments/new" element={<CreateMarketEnvironment />} />
        <Route path="/market/data" element={<MarketData />} />
        <Route path="/market/instruments" element={<Instruments />} />
        <Route path="/market/replay" element={<Replay />} />

        <Route path="/simulation/runs" element={<SimulationsList />} />
        <Route path="/simulation/configure" element={<ConfigureSimulation />} />
        <Route path="/simulation/run/:id" element={<RunSimulation />} />
        <Route path="/simulation/results/:id" element={<SimulationResults />} />
        <Route path="/simulation/calibrations" element={<Calibrations />} />
        <Route path="/simulation/models" element={<Models />} />

        <Route path="/trading/strategies" element={<Strategies />} />
        <Route path="/trading/strategies/new" element={<ConfigureStrategy />} />
        <Route path="/trading/strategies/:id" element={<ConfigureStrategy />} />
        <Route path="/trading/portfolios" element={<Portfolios />} />
        <Route path="/trading/portfolios/new" element={<CreatePortfolio />} />
        <Route path="/trading/replay/:id" element={<TradeReplay />} />

        <Route path="/risk/overview" element={<RiskOverview />} />
        <Route path="/risk/stress-testing" element={<StressTesting />} />
        <Route path="/risk/tda-analysis" element={<TdaAnalysis />} />
        <Route path="/risk/explanations" element={<Explanations />} />
        <Route path="/risk/composite" element={<CompositeRiskPage />} />
        <Route path="/risk/attribution" element={<Attribution />} />

        <Route path="/ml/models" element={<MLModelsPage />} />
        <Route path="/ml/predictions" element={<Predictions />} />
        <Route path="/ml/features" element={<Features />} />

        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/audit-log" element={<AuditLog />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/architecture" element={<Architecture />} />

        <Route path="/admin/users" element={<Users />} />
        <Route path="/admin/roles" element={<Roles />} />
        <Route path="/admin/system" element={<System />} />

        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
