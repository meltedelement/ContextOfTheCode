# Things we should remember
- We could make a dataReader class with the shared data format and the reader and have the other readers inherit from that like weatherReader
    - Did this with an ABC (Abstract data class), which i thought was only in java

- Have a unique identifier for each running of the program, like the mac address or something, my limerick reader says temp in ireland is c, my japan reader says temp in ireland is y.
    - Didnt use the mac address, as thats kinda complicated to get a standardised mac address considering we're using 3rd party sources and such, however i have a unique identifier area on all the things that we can fill in by habd

- It's good to know that the way im polling wikipedia here may not be 100% accurate in terms of timing,edits may fall into either side of a poll depending on when they were submitted from the user not in real time as i understand it, this is still much better than streaming in data from eventstreams im fairly sure, we can look at it again later


- [/] Build the data collector base class, test by extending it to the system data collector
- [kinda] finish the data model
- [ ] do the download queue