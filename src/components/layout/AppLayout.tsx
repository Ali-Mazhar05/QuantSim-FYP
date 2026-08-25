import { Outlet } from 'react-router-dom'
import DemoModeModal from '../modals/DemoModeModal'
import DemoControlBar from '../navigation/DemoControlBar'
import Sidebar from '../navigation/Sidebar'
import SystemActivityDrawer from '../navigation/SystemActivityDrawer'
import Topbar from '../navigation/Topbar'
import ToastStack from '../status/ToastStack'

export default function AppLayout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--color-bg-0)] text-[var(--color-text-primary)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <DemoControlBar />
        <main className="qs-scrollbar-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1600px] px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
      <SystemActivityDrawer />
      <ToastStack />
      <DemoModeModal />
    </div>
  )
}
