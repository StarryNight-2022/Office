Assume Kaihong possesses the code and systems for resource allocation and monitoring.
However, the system lacks adaptability—specifically regarding the handling of special events or contingencies, as well as special arrangements or considerations for key personnel.
Examples:
1. When a leader arrives, special arrangements are executed (e.g., turning on the air conditioning in advance); conversely, if the users are students or unrelated individuals, meeting room access or air conditioning might not be granted.
2. It requires the capability to manage scheduling based on specific conditions—such as using sensors to determine if a professor is on campus and assessing whether a meeting can be arranged based on student needs.
Focuses：
1. Long-Horizon
2. Event-based Better （ARE）（Compared with Function-Calling）
3. Adapability？
-------------------------
build Smart-building ARE (FAIRY, simple ReAct ARE) with a world model, APIs, simulated office (K1324), new scenarios, !!!
-------------------------
@欧阳琨 in your simulated environment for smart building, add tools/APIs for devices as well (e.g., humidifier, air filter, etc...)!!! and office devices, like printer etc.
-------------------------
Add 1 more mode!
1. CEO mode
2. Office hours mode
3. Conference mode (which could be a superset of CEO mode) 
Consider the preparation the Teachers do in our Center when we have a formal presentation, e.g., you need to print nametags for the speakers etc.
-------------------------
1. find a model for electricity consumption for our AC models in the office; a rough model would do (e.g., kW as a function of their fan level and temperature setting). 

2. Also, consider human comfort aspects in the world model. E.g., it might be cheaper in term of electric bills to open the AC before a meeting and more comfortable for people sitting in the breeze!!! These will need to be parameters of the world model/APIs/tools.

3. Consider the "physics" of the "climate" inside the room; these are also interconnected dynamics which MUST be modeled in your world model; find models that capture this (even if very simple, e.g., ask GPT to come up with a simple model for now). E.g., the more you run the AC, the dryer the air becomes, so using AC decisions would affect turning on the humidifier, etc!!!
Treat this as ABSOLUTE priority; we must have the world model for our K1324 and a working L1 scenario by Monday!
-------------------------
*** We should have a "generalization" to unseen rooms/scenarios exploration for the paper!

>> Same way the Xiaomi vacuum can scan a new room and start working, we can simply take a photo (new installation to a NEW room) and use a multimolda LLM to take a "World model" format and generate it for the NEW room (e.g., number of desks, chairs, meeting room, use purpose etc.). This is more of a demo in the paper (even if it partially fills in the info, and we still have to specific type of AC, etc.). But it will be very impactful as an exploration in the paper, yet very easy to do!

Here's the example: we have the digital twin for K1315, we take photos from K1316, and a multimodal LLM takes the code describing K1315 and generates the new one for K1316!
-------------------------
I like this visualization, we'll have it for our MobiCom paper for the K13th floor floorplan "World Model"  @欧阳琨 add to the TODOs.md