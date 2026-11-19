import { useLocation } from 'react-router-dom'

/** Shows the router's current path, so tests can check where a page sent the visitor. */
export default function LocationProbe() {
  const { pathname } = useLocation()
  return <div data-testid="location">{pathname}</div>
}
