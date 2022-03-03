# Proxmox-memory-balancer

This version of the load balancer has been tested on Proxmox Virtual Environment 6.4-8 and 7.1-10 with 400+ virtual machines.
![balancer_](https://user-images.githubusercontent.com/88323643/137877901-b00683e0-a37f-4ed5-8761-09fefc7dc171.png)

If you want the load balancer not to migrate some VM, connect any ISO image to it.

Mi first star! Woohoo!!

This project is unlikely to be further supported, as I am writing a new one. This will be an analogue of the automatic mode of Vmware DRS.
Stay tuned.

!!!
If HA is enabled in your cluster, the script cannot correctly determine the migration process. Just select the correct number of seconds in the last line of the script. In my case, it's 90 seconds.
