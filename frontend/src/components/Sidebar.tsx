import Navbar from './Navbar';

/**
 * Sidebar is an alias/wrapper for Navbar.
 * Page agents that import Sidebar will get the left rail navigation.
 */
export default function Sidebar() {
  return <Navbar />;
}
