Remote Access

- These two script are used to set up a remote access connection between two devices.
- It works on LAN
- It is not yet secured so dont access it to the internet

How does it work?
- It works using a client-server architecture
- A socket using IPv4 and TCP is created which sends and receives bytes
- The server(the device to be cpntrolled) sends the image to the client(the device which will control)
- The client sends the mouse and keyboard actions using a listener for both and sending the avrions on the socket for the server to receive them and perform them.
























