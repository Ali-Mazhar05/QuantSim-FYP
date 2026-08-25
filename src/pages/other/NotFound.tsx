import { Link } from 'react-router-dom'
import EmptyState from '../../components/status/EmptyState'
import { AlertOctagon } from 'lucide-react'
import Button from '../../components/forms/Button'

export default function NotFound() {
  return (
    <EmptyState
      icon={AlertOctagon}
      title="Page not found"
      description="This screen does not exist in the QuantSim POC."
      action={
        <Link to="/dashboard">
          <Button variant="secondary" size="sm">Return to Dashboard</Button>
        </Link>
      }
    />
  )
}
