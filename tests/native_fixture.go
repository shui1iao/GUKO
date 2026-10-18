// Standalone OFFLINE transport cancellation fixture; not shipped to users.
package main
import("os";"os/signal";"strconv";"syscall";"time")
func main(){
 if path:=os.Getenv("FIXTURE_CHILD_PID");path!=""{_ = os.WriteFile(path,[]byte(strconv.Itoa(os.Getpid())),0600)}
 signals:=make(chan os.Signal,1);signal.Notify(signals,syscall.SIGTERM,syscall.SIGINT,syscall.SIGHUP)
 select{case <-signals:case <-time.After(60*time.Second):}
}
